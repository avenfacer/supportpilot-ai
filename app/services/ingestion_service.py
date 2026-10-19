import hashlib
import logging
import re
from pathlib import Path

from app.ai.embedding_provider import EmbeddingProvider
from app.ai.errors import ProviderError
from app.core.config import PROJECT_ROOT
from app.repositories.base import KnowledgeRepository
from app.schemas.knowledge import ChunkRecord, DocumentRecord, IngestionError, IngestionReport
from app.services.chunking import ParsedDocument, parse_markdown

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".md", ".txt"}


def document_id_for(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "_", path.stem.lower()).strip("_")


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def embedding_text(parsed: ParsedDocument, section: str, content: str) -> str:
    return f"{parsed.title}\n{section}\n{content}"


class IngestionService:
    def __init__(
        self,
        repository: KnowledgeRepository,
        embedder: EmbeddingProvider,
        *,
        chunk_size: int,
        chunk_overlap: int,
    ):
        self._repo = repository
        self._embedder = embedder
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def ingest_directory(self, directory: Path, *, prune: bool = True) -> IngestionReport:
        report = IngestionReport()
        if not directory.is_dir():
            report.errors.append(
                IngestionError(source_path=str(directory), error="directory not found")
            )
            return report

        seen: set[str] = set()
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                seen.add(document_id_for(path))
                self._ingest_file(path, report)

        if prune:
            for doc in self._repo.list_documents():
                if doc.document_id not in seen:
                    self._repo.delete_document(doc.document_id)
                    report.deleted.append(doc.document_id)

        logger.info(
            "ingestion_finished",
            extra={
                "docs_created": len(report.created),
                "docs_updated": len(report.updated),
                "docs_unchanged": len(report.unchanged),
                "docs_deleted": len(report.deleted),
                "docs_failed": len(report.errors),
            },
        )
        return report

    def _ingest_file(self, path: Path, report: IngestionReport) -> None:
        source_path = display_path(path)
        document_id = document_id_for(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self._record_error(report, source_path, f"could not read file: {type(exc).__name__}")
            return

        # The embedding model and chunking settings are part of the fingerprint so that changing
        # either one re-embeds documents instead of keeping stale vectors.
        fingerprint = (
            f"{raw}\n--\n{self._embedder.name}:{self._embedder.model}:"
            f"{self._chunk_size}:{self._chunk_overlap}"
        )
        content_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        existing = self._repo.get_document(document_id)
        if existing and existing.content_hash == content_hash:
            report.unchanged.append(document_id)
            return

        parsed = parse_markdown(
            document_id=document_id,
            source_path=source_path,
            text=raw,
            chunk_size=self._chunk_size,
            overlap=self._chunk_overlap,
        )
        if not parsed.chunks:
            self._record_error(report, source_path, "document has no content")
            return

        try:
            # Embed everything before writing so a provider failure never leaves partial data.
            vectors = self._embedder.embed_documents(
                [embedding_text(parsed, c.section, c.content) for c in parsed.chunks]
            )
        except ProviderError as exc:
            self._record_error(report, source_path, f"embedding failed: {exc}")
            return

        chunks = [
            ChunkRecord(
                id=c.chunk_id,
                document_id=document_id,
                chunk_index=c.chunk_index,
                content=c.content,
                section=c.section,
                embedding=vector,
                metadata={
                    "title": parsed.title,
                    "source_path": source_path,
                    "section": c.section,
                    "chunk_index": c.chunk_index,
                    "char_count": len(c.content),
                    "embedding_provider": self._embedder.name,
                },
            )
            for c, vector in zip(parsed.chunks, vectors, strict=True)
        ]
        document = DocumentRecord(
            id=document_id, title=parsed.title, source_path=source_path, content_hash=content_hash
        )
        try:
            self._repo.replace_document(document, chunks)
        except Exception as exc:
            self._record_error(report, source_path, f"storage failed: {type(exc).__name__}")
            return

        (report.updated if existing else report.created).append(document_id)
        report.chunk_count += len(chunks)

    @staticmethod
    def _record_error(report: IngestionReport, source_path: str, error: str) -> None:
        logger.error("ingestion_error", extra={"source_path": source_path, "error": error})
        report.errors.append(IngestionError(source_path=source_path, error=error))
