import pytest

from app.repositories.memory import InMemoryOrderRepository, InMemoryTicketRepository
from app.schemas.order import OrderRecord
from app.services.order_service import (
    MockOrderClient,
    OrderApiUnavailable,
    OrderLookupStatus,
    OrderService,
)
from tests.conftest import ClientFactory, ScriptedLLM

ALEX = {"X-Demo-Customer-Id": "CUST-001"}
SAM = {"X-Demo-Customer-Id": "CUST-002"}


class FlakyClient:
    def __init__(self, repo: InMemoryOrderRepository, failures: int):
        self.repo = repo
        self.failures = failures
        self.calls = 0

    def fetch(self, order_id: str) -> OrderRecord | None:
        self.calls += 1
        if self.calls <= self.failures:
            raise OrderApiUnavailable("flaky")
        return self.repo.get(order_id)


# --- service level ------------------------------------------------------------------------


def test_owner_can_read_order_summary_without_customer_id(
    order_repo: InMemoryOrderRepository,
) -> None:
    result = OrderService(MockOrderClient(order_repo)).lookup("ORD-1002", "CUST-001")
    assert result.status is OrderLookupStatus.FOUND
    assert result.order is not None
    assert result.order.tracking_number == "NSX-TRK-100002"
    assert "customer_id" not in result.order.model_dump()


@pytest.mark.parametrize(
    ("order_id", "customer_id", "status"),
    [
        ("ORD-2001", "CUST-001", OrderLookupStatus.UNAUTHORIZED),
        ("ORD-9999", "CUST-001", OrderLookupStatus.NOT_FOUND),
    ],
)
def test_lookup_denies_or_misses_without_returning_data(
    order_repo: InMemoryOrderRepository, order_id: str, customer_id: str, status: OrderLookupStatus
) -> None:
    result = OrderService(MockOrderClient(order_repo)).lookup(order_id, customer_id)
    assert result.status is status
    assert result.order is None


@pytest.mark.parametrize(
    ("mode", "status"),
    [("timeout", OrderLookupStatus.TIMEOUT), ("unavailable", OrderLookupStatus.UNAVAILABLE)],
)
def test_upstream_failures_are_distinct_and_retried(
    order_repo: InMemoryOrderRepository, mode: str, status: OrderLookupStatus
) -> None:
    client = MockOrderClient(order_repo, failure_mode=mode)  # type: ignore[arg-type]
    result = OrderService(client, max_attempts=2).lookup("ORD-1002", "CUST-001")
    assert result.status is status
    assert result.attempts == 2


def test_transient_failure_recovers_on_retry(order_repo: InMemoryOrderRepository) -> None:
    client = FlakyClient(order_repo, failures=1)
    result = OrderService(client, max_attempts=2).lookup("ORD-1002", "CUST-001")
    assert result.status is OrderLookupStatus.FOUND
    assert client.calls == 2


# --- chat ---------------------------------------------------------------------------------


def test_chat_order_status_uses_mock_api_data(make_client: ClientFactory) -> None:
    body = (
        make_client()
        .post("/api/v1/chat", json={"message": "Where is order ORD-1002?"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "answered"
    assert "ORD-1002" in body["answer"]
    assert "shipped" in body["answer"]
    assert "NSX-TRK-100002" in body["answer"]
    assert "2026-10-21" in body["answer"]


def test_chat_never_invents_tracking_for_unshipped_order(make_client: ClientFactory) -> None:
    body = (
        make_client()
        .post("/api/v1/chat", json={"message": "Has ORD-1003 shipped yet?"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "answered"
    assert "tracking number isn't available yet" in body["answer"]
    assert "NSX-TRK" not in body["answer"]


def test_cross_customer_order_is_indistinguishable_from_missing(
    make_client: ClientFactory,
) -> None:
    client = make_client()
    other = client.post("/api/v1/chat", json={"message": "Where is ORD-2001?"}, headers=ALEX)
    missing = client.post("/api/v1/chat", json={"message": "Where is ORD-9999?"}, headers=ALEX)

    assert other.json()["status"] == "needs_clarification"
    assert "Camping Lantern" not in other.text and "NSX-TRK-200001" not in other.text
    assert other.json()["answer"].replace("2001", "X") == missing.json()["answer"].replace(
        "9999", "X"
    )


def test_model_cannot_choose_customer_identity(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        tool="lookup_order", arguments={"order_id": "ORD-2001", "customer_id": "CUST-002"}
    )
    body = (
        make_client(llm=llm)
        .post("/api/v1/chat", json={"message": "Show ORD-2001"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "needs_clarification"
    assert "Camping Lantern" not in body["answer"]


def test_order_question_without_identity_asks_to_sign_in(make_client: ClientFactory) -> None:
    body = make_client().post("/api/v1/chat", json={"message": "Where is ORD-1002?"}).json()
    assert body["status"] == "needs_clarification"
    assert "verify your identity" in body["answer"]
    assert "NSX-TRK" not in body["answer"]


def test_order_question_without_id_asks_for_it(make_client: ClientFactory) -> None:
    body = (
        make_client()
        .post("/api/v1/chat", json={"message": "Where is my order?"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "needs_clarification"
    assert "order ID" in body["answer"]


@pytest.mark.parametrize("mode", ["timeout", "unavailable"])
def test_order_api_failure_returns_tool_error_and_offers_handoff(
    make_client: ClientFactory, mode: str
) -> None:
    body = (
        make_client(mock_order_failure_mode=mode)
        .post("/api/v1/chat", json={"message": "Where is ORD-1002?"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "tool_error"
    assert body["needs_human"] is True
    assert "NSX-TRK" not in body["answer"] and "2026" not in body["answer"]


def test_invalid_tool_arguments_are_not_executed(
    make_client: ClientFactory, ticket_repo: InMemoryTicketRepository
) -> None:
    llm = ScriptedLLM(tool="create_support_request", arguments={"request_type": "refund_now"})
    body = (
        make_client(llm=llm)
        .post("/api/v1/chat", json={"message": "refund me"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "needs_clarification"
    assert ticket_repo.tickets == {}


def test_unknown_tool_is_not_executed(make_client: ClientFactory) -> None:
    llm = ScriptedLLM(tool="issue_refund", arguments={"order_id": "ORD-1001"})
    body = (
        make_client(llm=llm)
        .post("/api/v1/chat", json={"message": "refund ORD-1001"}, headers=ALEX)
        .json()
    )
    assert body["status"] == "needs_clarification"


# --- REST endpoint ------------------------------------------------------------------------


def test_orders_endpoint_enforces_ownership(make_client: ClientFactory) -> None:
    client = make_client()
    assert client.get("/api/v1/orders/ORD-1002", headers=ALEX).status_code == 200
    denied = client.get("/api/v1/orders/ORD-1002", headers=SAM)
    missing = client.get("/api/v1/orders/ORD-9999", headers=SAM)
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["error"]["message"] == missing.json()["error"]["message"]


def test_orders_endpoint_requires_identity(make_client: ClientFactory) -> None:
    client = make_client()
    assert client.get("/api/v1/orders/ORD-1002").status_code == 401
    bad = client.get("/api/v1/orders/ORD-1002", headers={"X-Demo-Customer-Id": "admin"})
    assert bad.status_code == 401


def test_demo_auth_can_be_disabled(make_client: ClientFactory) -> None:
    client = make_client(enable_demo_auth=False)
    assert client.get("/api/v1/orders/ORD-1002", headers=ALEX).status_code == 401


def test_orders_endpoint_reports_upstream_outage(make_client: ClientFactory) -> None:
    response = make_client(mock_order_failure_mode="unavailable").get(
        "/api/v1/orders/ORD-1002", headers=ALEX
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "order_service_unavailable"
