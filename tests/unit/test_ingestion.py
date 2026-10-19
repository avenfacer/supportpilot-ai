from pathlib import Path

import pytest

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.errors import ProviderError
from app.ai.fake_embedding import FakeEmbeddingProvider
from app.repositories.memory import InMemoryKnowledgeRepository
from app.services.ingestion_service import IngestionService


class FailingEmbedder(EmbeddingProvider):
    name = "failing"
    model = "failing"
    dimensions = 8

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError("simulated outage")


class WrongSizeEmbedder(FakeEmbeddingProvider):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        from app.ai.embedding_provider import validate_vectors

        vectors = [[0.1] * (self.dimensions - 1) for _ in texts]
        validate_vectors(vectors, len(texts), self.dimensions)
        return vectors


def _service(repo: InMemoryKnowledgeRepository, embedder: EmbeddingProvider) -> IngestionService:
    return IngestionService(repo, embedder, chunk_size=400, chunk_overlap=50)


@pytest.fixture
def kb_dir(tmp_path: Path) -> Path:
    (tmp_path / "shipping.md").write_text("# Shipping\n\n## Speed\n\nFast delivery.\n")
    (tmp_path / "returns.md").write_text("# Returns\n\n## Window\n\n30 days.\n")
    (tmp_path / "notes.pdf").write_bytes(b"ignored")
    return tmp_path


def test_ingestion_stores_chunks_with_metadata(kb_dir: Path) -> None:
    repo = InMemoryKnowledgeRepository()
    report = _service(repo, FakeEmbeddingProvider(16)).ingest_directory(kb_dir)

    assert report.ok
    assert sorted(report.created) == ["returns", "shipping"]
    chunk = repo.chunks["shipping"][0]
    assert chunk.id == "shipping:000"
    assert chunk.section == "Speed"
    assert chunk.metadata["title"] == "Shipping"
    assert chunk.metadata["chunk_index"] == 0
    assert len(chunk.embedding) == 16


def test_reingestion_is_idempotent_and_detects_changes(kb_dir: Path) -> None:
    repo = InMemoryKnowledgeRepository()
    service = _service(repo, FakeEmbeddingProvider(16))
    service.ingest_directory(kb_dir)

    second = service.ingest_directory(kb_dir)
    assert sorted(second.unchanged) == ["returns", "shipping"]
    assert sum(len(c) for c in repo.chunks.values()) == 2

    (kb_dir / "returns.md").write_text("# Returns\n\n## Window\n\n45 days.\n\n## Fees\n\nFree.\n")
    (kb_dir / "shipping.md").unlink()
    third = service.ingest_directory(kb_dir)
    assert third.updated == ["returns"]
    assert third.deleted == ["shipping"]
    assert [c.section for c in repo.chunks["returns"]] == ["Window", "Fees"]


def test_changing_embedding_model_or_chunking_forces_reembedding(kb_dir: Path) -> None:
    repo = InMemoryKnowledgeRepository()
    _service(repo, FakeEmbeddingProvider(16)).ingest_directory(kb_dir)

    class OtherModel(FakeEmbeddingProvider):
        model = "fake-hashing-v2"

    assert sorted(_service(repo, OtherModel(16)).ingest_directory(kb_dir).updated) == [
        "returns",
        "shipping",
    ]
    rechunked = IngestionService(repo, OtherModel(16), chunk_size=300, chunk_overlap=50)
    assert len(rechunked.ingest_directory(kb_dir).updated) == 2


def test_embedding_failure_is_reported_and_nothing_is_stored(kb_dir: Path) -> None:
    repo = InMemoryKnowledgeRepository()
    report = _service(repo, FailingEmbedder()).ingest_directory(kb_dir)

    assert not report.ok
    assert {e.source_path for e in report.errors} == {"returns.md", "shipping.md"}
    assert all("embedding failed" in e.error for e in report.errors)
    assert repo.documents == {}


def test_invalid_vectors_are_rejected_before_storage(kb_dir: Path) -> None:
    repo = InMemoryKnowledgeRepository()
    report = _service(repo, WrongSizeEmbedder(16)).ingest_directory(kb_dir)
    assert len(report.errors) == 2
    assert repo.chunks == {}


def test_failed_reingestion_does_not_prune_existing_document(kb_dir: Path) -> None:
    repo = InMemoryKnowledgeRepository()
    _service(repo, FakeEmbeddingProvider(16)).ingest_directory(kb_dir)
    (kb_dir / "returns.md").write_text("# Returns\n\n## Window\n\nChanged.\n")

    report = _service(repo, FailingEmbedder()).ingest_directory(kb_dir)
    assert report.deleted == []
    assert "returns" in repo.documents
