import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.fake_embedding import FakeEmbeddingProvider
from app.main import create_app
from app.models import SupportTicket
from app.repositories.sql import SqlKnowledgeRepository
from app.services.ingestion_service import IngestionService
from tests.conftest import make_settings

pytestmark = pytest.mark.integration

ALEX = {"X-Demo-Customer-Id": "CUST-001"}
SAM = {"X-Demo-Customer-Id": "CUST-002"}


@pytest.fixture
def client(db_session: Session, database_url: str, embedder: FakeEmbeddingProvider) -> TestClient:
    settings = make_settings(database_url=database_url)
    report = IngestionService(
        SqlKnowledgeRepository(db_session),
        embedder,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    ).ingest_directory(settings.knowledge_base_dir)
    assert report.ok
    return TestClient(create_app(settings, embedder=embedder))


def test_ready_reports_database_and_pgvector(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {"database": True, "pgvector": True}


def test_faq_answer_cites_sources_stored_in_postgres(client: TestClient) -> None:
    body = client.post("/api/v1/chat", json={"message": "When will I get my refund?"}).json()
    assert body["status"] == "answered"
    assert body["citations"][0]["document_id"] == "refunds"


def test_order_lookup_and_cross_customer_denial(client: TestClient) -> None:
    own = client.post("/api/v1/chat", json={"message": "Where is ORD-1002?"}, headers=ALEX)
    assert own.json()["status"] == "answered"
    assert "NSX-TRK-100002" in own.json()["answer"]

    other = client.post("/api/v1/chat", json={"message": "Where is ORD-1002?"}, headers=SAM)
    assert other.json()["status"] == "needs_clarification"
    assert "NSX-TRK" not in other.text
    assert client.get("/api/v1/orders/ORD-1002", headers=SAM).status_code == 404


def test_return_request_persists_pending_ticket(client: TestClient, db_session: Session) -> None:
    body = client.post(
        "/api/v1/chat", json={"message": "I want to return ORD-1001, wrong colour"}, headers=ALEX
    ).json()
    assert body["status"] == "handoff"

    stored = db_session.scalars(select(SupportTicket)).all()
    assert [t.id for t in stored] == [body["ticket_id"]]
    assert stored[0].status == "pending_human_review"
    assert stored[0].order_id == "ORD-1001"

    ticket = client.get(f"/api/v1/tickets/{body['ticket_id']}", headers=ALEX).json()
    assert ticket["status"] == "pending_human_review"
    assert client.get(f"/api/v1/tickets/{body['ticket_id']}", headers=SAM).status_code == 404


def test_admin_sources_endpoint_requires_token(database_url: str, db_session: Session) -> None:
    app = create_app(
        make_settings(database_url=database_url, enable_admin_endpoints=True, admin_token="t0ken")
    )
    client = TestClient(app)
    assert client.get("/api/v1/knowledge/sources").status_code == 403
    response = client.get("/api/v1/knowledge/sources", headers={"X-Admin-Token": "t0ken"})
    assert response.status_code == 200
