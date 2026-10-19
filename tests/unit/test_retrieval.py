import pytest

from app.ai.fake_embedding import FakeEmbeddingProvider
from app.repositories.memory import InMemoryKnowledgeRepository
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService
from tests.conftest import FIXTURES_DIR


@pytest.mark.parametrize(
    ("query", "expected_document"),
    [
        ("How long does standard shipping take?", "shipping"),
        ("How many days do I have to return an item?", "returns"),
        ("Can I cancel an order that already shipped?", "cancellations"),
        ("When will I get my refund?", "refunds"),
        ("Is there a warranty on headphones?", "warranty_faq"),
        ("What are your support hours?", "contact_escalation"),
        ("Do you ship to Canada?", "shipping"),
    ],
)
def test_known_questions_retrieve_expected_source(
    retrieval: RetrievalService, query: str, expected_document: str
) -> None:
    result = retrieval.retrieve(query)
    assert result.sufficient
    assert result.chunks[0].document_id == expected_document
    assert result.chunks[0].document_title
    assert result.chunks[0].source_path.endswith(f"{expected_document}.md")


@pytest.mark.parametrize(
    "query",
    ["What is the capital of France?", "Write me a poem about cats", "Who won the football game?"],
)
def test_unrelated_questions_return_insufficient_evidence(
    retrieval: RetrievalService, query: str
) -> None:
    result = retrieval.retrieve(query)
    assert not result.sufficient
    assert result.chunks == []


def test_results_are_ordered_and_respect_threshold(retrieval: RetrievalService) -> None:
    result = retrieval.retrieve("refund timeline")
    scores = [c.score for c in result.chunks]
    assert scores == sorted(scores, reverse=True)
    assert all(s >= retrieval.min_score for s in scores)
    assert len(result.candidates) <= retrieval.top_k


def test_empty_query_returns_no_chunks(retrieval: RetrievalService) -> None:
    assert retrieval.retrieve("   ").chunks == []


def test_chunks_containing_injection_are_quarantined(embedder: FakeEmbeddingProvider) -> None:
    repo = InMemoryKnowledgeRepository()
    IngestionService(repo, embedder, chunk_size=800, chunk_overlap=100).ingest_directory(
        FIXTURES_DIR / "poisoned_kb"
    )
    service = RetrievalService(repo, embedder, top_k=4, min_score=0.1)

    result = service.retrieve("What is the refund policy for gift cards?")
    assert result.quarantined_ids
    assert all("ignore" not in c.content.lower() for c in result.chunks)
