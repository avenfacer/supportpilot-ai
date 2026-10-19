from typing import Protocol

from app.schemas.knowledge import ChunkRecord, DocumentRecord, RetrievedChunk, SourceDocument
from app.schemas.order import OrderRecord
from app.schemas.ticket import TicketRecord


class KnowledgeRepository(Protocol):
    def get_document(self, document_id: str) -> DocumentRecord | None: ...

    def list_documents(self) -> list[SourceDocument]: ...

    def replace_document(self, document: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        """Upsert a document and atomically replace all of its chunks."""
        ...

    def delete_document(self, document_id: str) -> None: ...

    def search(self, embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        """Return the top_k chunks ordered by cosine similarity (highest first)."""
        ...


class OrderRepository(Protocol):
    def get(self, order_id: str) -> OrderRecord | None: ...


class TicketRepository(Protocol):
    def create(self, ticket: TicketRecord) -> TicketRecord: ...

    def get(self, ticket_id: str) -> TicketRecord | None: ...
