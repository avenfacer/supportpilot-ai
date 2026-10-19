"""In-memory repository implementations.

Used by the unit tests and the offline evaluation harness so they run without a database.
The application itself always uses the SQL repositories.
"""

import math

from app.schemas.knowledge import ChunkRecord, DocumentRecord, RetrievedChunk, SourceDocument
from app.schemas.order import OrderRecord
from app.schemas.ticket import TicketRecord


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self.documents: dict[str, DocumentRecord] = {}
        self.chunks: dict[str, list[ChunkRecord]] = {}

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self.documents.get(document_id)

    def list_documents(self) -> list[SourceDocument]:
        return [
            SourceDocument(
                document_id=d.id,
                title=d.title,
                source_path=d.source_path,
                chunk_count=len(self.chunks.get(d.id, [])),
            )
            for d in sorted(self.documents.values(), key=lambda d: d.id)
        ]

    def replace_document(self, document: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        self.documents[document.id] = document
        self.chunks[document.id] = list(chunks)

    def delete_document(self, document_id: str) -> None:
        self.documents.pop(document_id, None)
        self.chunks.pop(document_id, None)

    def search(self, embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        for doc_id, chunks in self.chunks.items():
            doc = self.documents[doc_id]
            for c in chunks:
                scored.append(
                    RetrievedChunk(
                        chunk_id=c.id,
                        document_id=doc_id,
                        document_title=doc.title,
                        source_path=doc.source_path,
                        section=c.section,
                        chunk_index=c.chunk_index,
                        content=c.content,
                        score=cosine_similarity(embedding, c.embedding),
                    )
                )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:top_k]


class InMemoryOrderRepository:
    def __init__(self, orders: list[OrderRecord] | None = None) -> None:
        self.orders = {o.order_id: o for o in orders or []}

    def get(self, order_id: str) -> OrderRecord | None:
        return self.orders.get(order_id)


class InMemoryTicketRepository:
    def __init__(self) -> None:
        self.tickets: dict[str, TicketRecord] = {}

    def create(self, ticket: TicketRecord) -> TicketRecord:
        if ticket.id in self.tickets:
            raise ValueError("duplicate ticket id")
        self.tickets[ticket.id] = ticket
        return ticket

    def get(self, ticket_id: str) -> TicketRecord | None:
        return self.tickets.get(ticket_id)
