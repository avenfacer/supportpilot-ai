"""Support orchestrator: deterministic guardrails, one model-chosen tool, validated execution.

The model only *proposes* a tool call. This module validates it against the registry, enforces
identity and ownership, executes it, and builds the response from validated data only.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.ai.grounded_answer import AnswerOutcome, GroundedAnswerer
from app.ai.llm_provider import LLMProvider, TokenUsage
from app.ai.prompts import load_prompt
from app.ai.safety import is_human_request, is_sensitive_request, looks_like_prompt_injection
from app.core.security import DEMO_CUSTOMER_HEADER, CustomerContext
from app.schemas.chat import ChatResponse, ChatStatus, Citation
from app.schemas.knowledge import RetrievedChunk
from app.schemas.order import OrderSummary
from app.schemas.ticket import RequestType
from app.services.order_service import OrderLookupStatus, OrderService
from app.services.retrieval_service import RetrievalService
from app.services.ticket_service import TicketCreationError, TicketService
from app.tools.conversation import AskClarificationArgs, SearchKnowledgeArgs
from app.tools.names import ToolName
from app.tools.order_lookup import LookupOrderArgs
from app.tools.registry import ToolRegistry, ToolValidationError
from app.tools.support_request import CreateSupportRequestArgs, RequestHumanHandoffArgs

logger = logging.getLogger(__name__)

SIGN_IN_MESSAGE = (
    "To help with a specific order I need to verify your identity first. Please sign in and try "
    f"again. (Demo: send the {DEMO_CUSTOMER_HEADER} header, e.g. CUST-001.)"
)
NOT_IN_KB_MESSAGE = (
    "I couldn't find this in Northstar Shop's help articles, so I don't want to guess. "
    "I can connect you with a human support agent if you'd like."
)
UNSUPPORTED_MESSAGE = (
    "I can only help with Northstar Shop orders, shipping, returns, cancellations, refunds, "
    "warranty, and contact questions."
)
INJECTION_MESSAGE = (
    "I can't help with that request. I can answer questions about Northstar Shop policies "
    "and your orders."
)
INVALID_TOOL_MESSAGE = (
    "I couldn't process that request. Could you rephrase it, and include the order ID "
    "(for example ORD-1234) if it's about an order?"
)
ORDER_API_DOWN_MESSAGE = (
    "Order lookup is temporarily unavailable, so I can't confirm any order details right now. "
    "Please try again in a few minutes, or I can hand this over to a human support agent."
)
TICKET_FAILED_MESSAGE = (
    "I wasn't able to submit your request because of a system problem, so nothing has been "
    "submitted yet. Please try again later or contact Northstar support directly."
)
_POLICY_QUERIES = {
    RequestType.RETURN: "How to start a return, return window and items that cannot be returned",
    RequestType.CANCELLATION: "When can an order be cancelled and orders that have already shipped",
}
_SHIPPED_STATUSES = {"shipped", "out_for_delivery", "delivered"}


@dataclass
class TurnResult:
    response: ChatResponse
    tool: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


@dataclass
class _Turn:
    message: str
    customer: CustomerContext | None
    conversation_id: str | None
    result: TurnResult

    def respond(self, status: ChatStatus, answer: str, **kwargs: object) -> TurnResult:
        self.result.response = ChatResponse(
            status=status, answer=answer, conversation_id=self.conversation_id, **kwargs
        )
        return self.result


def describe_order(order: OrderSummary) -> str:
    status = order.status.replace("_", " ")
    parts = [f"Order {order.order_id} is currently {status}."]
    if order.status == "delivered":
        if order.estimated_delivery:
            parts.append(f"It was scheduled for delivery on {order.estimated_delivery}.")
    elif order.status != "cancelled":
        if order.estimated_delivery:
            parts.append(f"Estimated delivery: {order.estimated_delivery}.")
        else:
            parts.append("An estimated delivery date isn't available yet.")
    if order.tracking_number:
        parts.append(f"Tracking number: {order.tracking_number}.")
    elif order.status != "cancelled":
        parts.append("A tracking number isn't available yet; it is added once the order ships.")
    items = ", ".join(f"{i.quantity}x {i.name}" for i in order.items)
    if items:
        parts.append(f"Items: {items}.")
    return " ".join(parts)


class SupportOrchestrator:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        registry: ToolRegistry,
        retrieval: RetrievalService,
        answerer: GroundedAnswerer,
        order_service: OrderService,
        ticket_service: TicketService,
    ):
        self._llm = llm
        self._registry = registry
        self._retrieval = retrieval
        self._answerer = answerer
        self._orders = order_service
        self._tickets = ticket_service
        self._planner_prompt = load_prompt("planner")

    @contextmanager
    def _timed(self, turn: _Turn, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            turn.result.timings_ms[name] = round(turn.result.timings_ms.get(name, 0) + elapsed, 2)

    def handle(
        self, message: str, customer: CustomerContext | None, conversation_id: str | None = None
    ) -> TurnResult:
        placeholder = ChatResponse(status=ChatStatus.UNSUPPORTED, answer="")
        turn = _Turn(message, customer, conversation_id, TurnResult(response=placeholder))

        if looks_like_prompt_injection(message):
            logger.warning("prompt_injection_blocked", extra={"stage": "user_message"})
            return turn.respond(ChatStatus.UNSUPPORTED, INJECTION_MESSAGE)
        if is_human_request(message):
            return self._handoff(turn, "customer_requested_human", "Customer asked for a human.")
        if is_sensitive_request(message):
            return self._handoff(turn, "sensitive_issue", "Sensitive issue requires a human.")

        with self._timed(turn, "plan"):
            plan = self._llm.plan(
                system_prompt=self._planner_prompt,
                user_message=message,
                tools=self._registry.specs(),
            )
        turn.result.usage.add(plan.usage)
        if plan.tool_call is None:
            return turn.respond(ChatStatus.NEEDS_CLARIFICATION, INVALID_TOOL_MESSAGE)

        try:
            call = self._registry.validate(plan.tool_call)
        except ToolValidationError as exc:
            turn.result.tool = f"rejected:{exc.code}"
            return turn.respond(ChatStatus.NEEDS_CLARIFICATION, INVALID_TOOL_MESSAGE)

        turn.result.tool = call.name.value
        args = call.args
        if call.name is ToolName.SEARCH_KNOWLEDGE:
            assert isinstance(args, SearchKnowledgeArgs)
            return self._answer_from_knowledge(turn, args.query)
        if call.name is ToolName.LOOKUP_ORDER:
            assert isinstance(args, LookupOrderArgs)
            return self._lookup_order(turn, args.order_id)
        if call.name is ToolName.CREATE_SUPPORT_REQUEST:
            assert isinstance(args, CreateSupportRequestArgs)
            return self._create_support_request(turn, args)
        if call.name is ToolName.REQUEST_HUMAN_HANDOFF:
            assert isinstance(args, RequestHumanHandoffArgs)
            return self._handoff(turn, "model_escalation", args.reason)
        if call.name is ToolName.ASK_CLARIFICATION:
            assert isinstance(args, AskClarificationArgs)
            return turn.respond(ChatStatus.NEEDS_CLARIFICATION, args.question)
        return turn.respond(ChatStatus.UNSUPPORTED, UNSUPPORTED_MESSAGE)

    # --- knowledge -------------------------------------------------------------------------

    def _retrieve(self, turn: _Turn, query: str) -> list[RetrievedChunk]:
        with self._timed(turn, "retrieval"):
            result = self._retrieval.retrieve(query)
        turn.result.retrieved_chunk_ids.extend(c.chunk_id for c in result.chunks)
        return result.chunks

    def _answer_from_knowledge(self, turn: _Turn, query: str) -> TurnResult:
        chunks = self._retrieve(turn, query)
        if not chunks:
            return turn.respond(
                ChatStatus.UNSUPPORTED,
                NOT_IN_KB_MESSAGE,
                needs_human=True,
                handoff_reason="insufficient_evidence",
            )
        with self._timed(turn, "generation"):
            grounded = self._answerer.answer(turn.message, chunks)
        turn.result.usage.add(grounded.usage)

        if grounded.outcome is AnswerOutcome.CONFLICTING:
            return self._handoff(turn, "conflicting_policy", "Retrieved policy text conflicts.")
        if grounded.outcome is AnswerOutcome.INSUFFICIENT:
            return turn.respond(
                ChatStatus.UNSUPPORTED,
                NOT_IN_KB_MESSAGE,
                needs_human=True,
                handoff_reason="insufficient_evidence",
            )
        return turn.respond(
            ChatStatus.ANSWERED,
            grounded.answer,
            citations=[Citation.from_chunk(c) for c in grounded.citations],
        )

    # --- orders ----------------------------------------------------------------------------

    def _lookup_order(self, turn: _Turn, order_id: str) -> TurnResult:
        if turn.customer is None:
            return turn.respond(ChatStatus.NEEDS_CLARIFICATION, SIGN_IN_MESSAGE)
        with self._timed(turn, "tool"):
            result = self._orders.lookup(order_id, turn.customer.customer_id)
        if result.status is OrderLookupStatus.FOUND and result.order:
            return turn.respond(ChatStatus.ANSWERED, describe_order(result.order))
        if result.is_failure:
            return turn.respond(
                ChatStatus.TOOL_ERROR,
                ORDER_API_DOWN_MESSAGE,
                needs_human=True,
                handoff_reason="order_api_unavailable",
            )
        # Not found and not owned produce the same answer so order existence is not leaked.
        return turn.respond(ChatStatus.NEEDS_CLARIFICATION, _order_not_found(order_id))

    # --- requests and handoff --------------------------------------------------------------

    def _create_support_request(self, turn: _Turn, args: CreateSupportRequestArgs) -> TurnResult:
        request_type = RequestType(args.request_type)
        verb = "return" if request_type is RequestType.RETURN else "cancel"
        if turn.customer is None:
            return turn.respond(ChatStatus.NEEDS_CLARIFICATION, SIGN_IN_MESSAGE)
        if args.order_id is None:
            return turn.respond(
                ChatStatus.NEEDS_CLARIFICATION,
                f"Which order would you like to {verb}? Please share the order ID "
                "(for example ORD-1234).",
            )

        with self._timed(turn, "tool"):
            lookup = self._orders.lookup(args.order_id, turn.customer.customer_id)
        if lookup.is_failure:
            return turn.respond(
                ChatStatus.TOOL_ERROR,
                ORDER_API_DOWN_MESSAGE,
                needs_human=True,
                handoff_reason="order_api_unavailable",
            )
        order = lookup.order
        if lookup.status is not OrderLookupStatus.FOUND or order is None:
            return turn.respond(ChatStatus.NEEDS_CLARIFICATION, _order_not_found(args.order_id))

        if request_type is RequestType.CANCELLATION and order.status == "cancelled":
            return turn.respond(
                ChatStatus.ANSWERED,
                f"Order {order.order_id} is already cancelled, so no new request was created.",
            )

        policy_chunks = self._retrieve(turn, _POLICY_QUERIES[request_type])[:2]
        notes = _eligibility_notes(request_type, order)
        try:
            with self._timed(turn, "ticket"):
                ticket = self._tickets.create_pending(
                    customer_id=turn.customer.customer_id,
                    request_type=request_type,
                    order_id=order.order_id,
                    reason=args.reason,
                    summary=(
                        f"{request_type.value.title()} request for {order.order_id} "
                        f"(order status: {order.status}) submitted via chat assistant. "
                        f"Customer reason: {args.reason}"
                    ),
                )
        except TicketCreationError:
            return turn.respond(
                ChatStatus.TOOL_ERROR,
                TICKET_FAILED_MESSAGE,
                needs_human=True,
                handoff_reason="ticket_creation_failed",
            )

        action = "returned or refunded" if request_type is RequestType.RETURN else "cancelled"
        answer = " ".join(
            [
                f"I've submitted a {request_type.value} request for order {order.order_id} "
                f"(reference {ticket.id}).",
                f"A human support agent must review it: nothing has been {action} yet, and "
                "approval isn't guaranteed.",
                *notes,
                "The relevant policy sections are cited below." if policy_chunks else "",
            ]
        ).strip()
        return turn.respond(
            ChatStatus.HANDOFF,
            answer,
            citations=[Citation.from_chunk(c) for c in policy_chunks],
            ticket_id=ticket.id,
            needs_human=True,
            handoff_reason="approval_required",
        )

    def _handoff(self, turn: _Turn, reason_code: str, detail: str) -> TurnResult:
        if turn.result.tool is None:
            turn.result.tool = f"guardrail:{reason_code}"
        if turn.customer is None:
            return turn.respond(
                ChatStatus.HANDOFF,
                "A human support agent should help with this. Please sign in or contact "
                "Northstar support directly so an agent can follow up with you.",
                needs_human=True,
                handoff_reason=reason_code,
            )
        try:
            ticket = self._tickets.create_pending(
                customer_id=turn.customer.customer_id,
                request_type=RequestType.OTHER,
                order_id=None,
                reason=detail,
                summary=f"Handoff ({reason_code}) from chat assistant. Last message: "
                f"{turn.message[:300]}",
            )
        except TicketCreationError:
            return turn.respond(
                ChatStatus.TOOL_ERROR,
                TICKET_FAILED_MESSAGE,
                needs_human=True,
                handoff_reason="ticket_creation_failed",
            )
        return turn.respond(
            ChatStatus.HANDOFF,
            f"I've passed this to a human support agent (reference {ticket.id}). They will "
            "follow up with you during support hours, so you won't need to repeat yourself.",
            ticket_id=ticket.id,
            needs_human=True,
            handoff_reason=reason_code,
        )


def _order_not_found(order_id: str) -> str:
    return (
        f"I couldn't find order {order_id} on your account. Please double-check the order ID "
        "(for example ORD-1234)."
    )


def _eligibility_notes(request_type: RequestType, order: OrderSummary) -> list[str]:
    status = order.status.replace("_", " ")
    if request_type is RequestType.CANCELLATION and order.status in _SHIPPED_STATUSES:
        return [
            f"Note: this order is already {status}, which usually affects whether it can still "
            "be cancelled; the agent will advise on your options."
        ]
    if request_type is RequestType.RETURN and order.status != "delivered":
        return [
            f"Note: this order is currently {status}, not delivered yet; the agent will advise "
            "on your options."
        ]
    return []
