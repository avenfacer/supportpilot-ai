import logging
import time

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.errors import ProviderError, ProviderTimeoutError
from app.ai.grounded_answer import GroundedAnswerer
from app.ai.llm_provider import LLMProvider
from app.ai.orchestrator import SupportOrchestrator, TurnResult
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.security import CustomerContext
from app.repositories.base import KnowledgeRepository, OrderRepository, TicketRepository
from app.schemas.chat import ChatRequest
from app.services.order_service import MockOrderClient, OrderService
from app.services.retrieval_service import RetrievalService
from app.services.ticket_service import TicketService
from app.tools.registry import default_registry

logger = logging.getLogger(__name__)

AI_UNAVAILABLE_MESSAGE = (
    "The support assistant is temporarily unavailable, so I can't answer reliably right now. "
    "Please try again shortly."
)


class ChatService:
    def __init__(self, orchestrator: SupportOrchestrator):
        self._orchestrator = orchestrator

    def handle(self, request: ChatRequest, customer: CustomerContext | None) -> TurnResult:
        started = time.perf_counter()
        try:
            result = self._orchestrator.handle(request.message, customer, request.conversation_id)
        except ProviderError as exc:
            logger.error(
                "chat_provider_failure",
                extra={
                    "error_type": type(exc).__name__,
                    "timeout": isinstance(exc, ProviderTimeoutError),
                },
            )
            raise ServiceUnavailableError(
                "ai_temporarily_unavailable", AI_UNAVAILABLE_MESSAGE
            ) from exc

        result.timings_ms["total"] = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "chat_turn",
            extra={
                "status": result.response.status.value,
                "tool": result.tool,
                "needs_human": result.response.needs_human,
                "ticket_id": result.response.ticket_id,
                "citations": [c.source_id for c in result.response.citations],
                "customer_id": customer.customer_id if customer else None,
                "timings_ms": result.timings_ms,
                "prompt_tokens": result.usage.prompt_tokens,
                "completion_tokens": result.usage.completion_tokens,
            },
        )
        return result


def build_order_service(orders: OrderRepository, settings: Settings) -> OrderService:
    return OrderService(
        MockOrderClient(orders, settings.mock_order_failure_mode),
        max_attempts=settings.order_api_max_attempts,
    )


def build_chat_service(
    *,
    settings: Settings,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    knowledge: KnowledgeRepository,
    orders: OrderRepository,
    tickets: TicketRepository,
    order_service: OrderService | None = None,
) -> ChatService:
    retrieval = RetrievalService(
        knowledge,
        embedder,
        top_k=settings.retrieval_top_k,
        min_score=settings.effective_min_score,
    )
    orchestrator = SupportOrchestrator(
        llm=llm,
        registry=default_registry(),
        retrieval=retrieval,
        answerer=GroundedAnswerer(llm),
        order_service=order_service or build_order_service(orders, settings),
        ticket_service=TicketService(tickets),
    )
    return ChatService(orchestrator)
