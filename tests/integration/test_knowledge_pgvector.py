import pytest
from sqlalchemy.orm import Session

from app.ai.fake_embedding import FakeEmbeddingProvider
from app.core.config import Settings
from app.repositories.sql import SqlKnowledgeRepository
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService

pytestmark = pytest.mark.integration


def test_ingest_and_search_with_pgvector(
    db_session: Session, settings: Settings, embedder: FakeEmbeddingProvider
) -> None:
    repo = SqlKnowledgeRepository(db_session)
    service = IngestionService(
        repo, embedder, chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
    )

    first = service.ingest_directory(settings.knowledge_base_dir)
    assert first.ok and len(first.created) == 6
    second = service.ingest_directory(settings.knowledge_base_dir)
    assert len(second.unchanged) == 6 and second.chunk_count == 0
    assert sum(d.chunk_count for d in repo.list_documents()) == first.chunk_count

    retrieval = RetrievalService(
        repo, embedder, top_k=settings.retrieval_top_k, min_score=settings.effective_min_score
    )
    hit = retrieval.retrieve("When will I get my refund?")
    assert hit.chunks[0].document_id == "refunds"
    assert hit.chunks[0].document_title == "Refunds"
    assert retrieval.retrieve("What is the capital of France?").chunks == []
