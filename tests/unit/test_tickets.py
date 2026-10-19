import pytest

from app.repositories.memory import InMemoryTicketRepository
from app.schemas.ticket import RequestType, TicketRecord, TicketStatus
from app.services.ticket_service import TicketCreationError, TicketService
from tests.conftest import ClientFactory, ScriptedLLM

ALEX = {"X-Demo-Customer-Id": "CUST-001"}
SAM = {"X-Demo-Customer-Id": "CUST-002"}


class BrokenTicketRepository(InMemoryTicketRepository):
    def create(self, ticket: TicketRecord) -> TicketRecord:
        raise RuntimeError("database is down")


def _chat(client, message: str, headers: dict[str, str] | None = None) -> dict:  # type: ignore[no-untyped-def]
    return client.post("/api/v1/chat", json={"message": message}, headers=headers or {}).json()


# --- service ------------------------------------------------------------------------------


def test_tickets_always_start_pending_and_are_redacted() -> None:
    service = TicketService(InMemoryTicketRepository())
    ticket = service.create_pending(
        customer_id="CUST-001",
        request_type=RequestType.RETURN,
        order_id="ORD-1001",
        reason="Too small. Email me at alex@example.com or call 555-123-4567.",
        summary="Return request",
    )
    assert ticket.status is TicketStatus.PENDING_HUMAN_REVIEW
    assert ticket.id.startswith("TKT-")
    assert "alex@example.com" not in ticket.reason
    assert "555-123-4567" not in ticket.reason


def test_ticket_is_only_visible_to_its_owner() -> None:
    service = TicketService(InMemoryTicketRepository())
    ticket = service.create_pending(
        customer_id="CUST-001",
        request_type=RequestType.OTHER,
        order_id=None,
        reason="x",
        summary="y",
    )
    assert service.get_for_customer(ticket.id, "CUST-001") is not None
    assert service.get_for_customer(ticket.id, "CUST-002") is None


def test_repository_failure_raises_ticket_creation_error() -> None:
    with pytest.raises(TicketCreationError):
        TicketService(BrokenTicketRepository()).create_pending(
            customer_id="CUST-001",
            request_type=RequestType.RETURN,
            order_id=None,
            reason="x",
            summary="y",
        )


def test_service_has_no_status_transition_api() -> None:
    public = {name for name in dir(TicketService) if not name.startswith("_")}
    assert public == {"create_pending", "get_for_customer"}


# --- chat workflow ------------------------------------------------------------------------


def test_return_request_creates_only_a_pending_ticket(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    body = _chat(make_client(), "I want to return order ORD-1001, the bottles leak.", ALEX)

    assert body["status"] == "handoff"
    assert body["needs_human"] is True
    assert body["handoff_reason"] == "approval_required"
    ticket = ticket_repo.tickets[body["ticket_id"]]
    assert ticket.status is TicketStatus.PENDING_HUMAN_REVIEW
    assert ticket.request_type is RequestType.RETURN
    assert ticket.order_id == "ORD-1001"
    assert ticket.customer_id == "CUST-001"
    assert "nothing has been returned or refunded yet" in body["answer"]
    assert body["citations"] and all(c["document_id"] == "returns" for c in body["citations"])


def test_cancellation_of_shipped_order_is_flagged_but_still_pending(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    body = _chat(make_client(), "Please cancel my order ORD-1002", ALEX)
    assert body["status"] == "handoff"
    assert "already shipped" in body["answer"]
    assert "nothing has been cancelled yet" in body["answer"]
    assert ticket_repo.tickets[body["ticket_id"]].status is TicketStatus.PENDING_HUMAN_REVIEW
    assert all(c["document_id"] == "cancellations" for c in body["citations"])


def test_already_cancelled_order_does_not_create_ticket(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    body = _chat(make_client(), "I want to cancel ORD-2002", SAM)
    assert body["status"] == "answered"
    assert body["ticket_id"] is None
    assert ticket_repo.tickets == {}


def test_request_for_another_customers_order_creates_nothing(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    body = _chat(make_client(), "I want to return ORD-2001", ALEX)
    assert body["status"] == "needs_clarification"
    assert ticket_repo.tickets == {}


def test_request_without_order_id_asks_for_it(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    body = _chat(make_client(), "I'd like to cancel my order", ALEX)
    assert body["status"] == "needs_clarification"
    assert "order ID" in body["answer"]
    assert ticket_repo.tickets == {}


def test_model_cannot_set_ticket_status(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    llm = ScriptedLLM(
        tool="create_support_request",
        arguments={
            "request_type": "return",
            "order_id": "ORD-1001",
            "reason": "x",
            "status": "approved",
        },
    )
    body = _chat(make_client(llm=llm), "return ORD-1001", ALEX)
    assert body["status"] == "needs_clarification"
    assert ticket_repo.tickets == {}


def test_ticket_failure_is_not_reported_as_success(
    make_client: ClientFactory,
    ticket_repo: InMemoryTicketRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(ticket: TicketRecord) -> TicketRecord:
        raise RuntimeError("db down")

    monkeypatch.setattr(ticket_repo, "create", fail)
    body = _chat(make_client(), "I want to return order ORD-1001", ALEX)
    assert body["status"] == "tool_error"
    assert body["ticket_id"] is None
    assert "nothing has been submitted" in body["answer"]


# --- handoff ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("Can I talk to a human please?", "customer_requested_human"),
        ("I see an unauthorized charge on my card from your store", "sensitive_issue"),
        ("The speaker caught fire while charging", "sensitive_issue"),
    ],
)
def test_handoff_creates_pending_ticket_for_signed_in_customer(
    make_client: ClientFactory,
    ticket_repo: InMemoryTicketRepository,
    message: str,
    reason: str,
) -> None:
    body = _chat(make_client(), message, ALEX)
    assert body["status"] == "handoff"
    assert body["handoff_reason"] == reason
    ticket = ticket_repo.tickets[body["ticket_id"]]
    assert ticket.request_type is RequestType.OTHER
    assert ticket.status is TicketStatus.PENDING_HUMAN_REVIEW


def test_anonymous_handoff_does_not_create_ticket(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    body = _chat(make_client(), "I want to speak to a real person")
    assert body["status"] == "handoff"
    assert body["ticket_id"] is None
    assert ticket_repo.tickets == {}


# --- REST endpoint ------------------------------------------------------------------------


def test_ticket_endpoint_enforces_ownership(make_client: ClientFactory) -> None:
    client = make_client()
    ticket_id = _chat(client, "I want to return order ORD-1001", ALEX)["ticket_id"]

    own = client.get(f"/api/v1/tickets/{ticket_id}", headers=ALEX)
    assert own.status_code == 200
    assert own.json()["status"] == "pending_human_review"
    assert "customer_id" not in own.json()

    assert client.get(f"/api/v1/tickets/{ticket_id}", headers=SAM).status_code == 404
    assert client.get(f"/api/v1/tickets/{ticket_id}").status_code == 401
    assert client.get("/api/v1/tickets/not-a-ticket", headers=ALEX).status_code == 422
