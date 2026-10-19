"""PostgreSQL/pgvector implementations of the repository protocols."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgeDocument, Order, SupportTicket
from app.schemas.knowledge import ChunkRecord, DocumentRecord, RetrievedChunk, SourceDocument
from app.schemas.order import OrderItem, OrderRecord
from app.schemas.ticket import RequestType, TicketRecord, TicketStatus


class SqlKnowledgeRepository:
    def __init__(self, session: Session):
        self._session = session

    def get_document(self, document_id: str) -> DocumentRecord | None:
        doc = self._session.get(KnowledgeDocument, document_id)
        if doc is None:
            return None
        return DocumentRecord(
            id=doc.id, title=doc.title, source_path=doc.source_path, content_hash=doc.content_hash
        )

    def list_documents(self) -> list[SourceDocument]:
        stmt = (
            select(KnowledgeDocument, func.count(KnowledgeChunk.id))
            .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .group_by(KnowledgeDocument.id)
            .order_by(KnowledgeDocument.id)
        )
        return [
            SourceDocument(
                document_id=doc.id, title=doc.title, source_path=doc.source_path, chunk_count=count
            )
            for doc, count in self._session.execute(stmt).all()
        ]

    def replace_document(self, document: DocumentRecord, chunks: list[ChunkRecord]) -> None:
        try:
            existing = self._session.get(KnowledgeDocument, document.id)
            if existing is None:
                self._session.add(
                    KnowledgeDocument(
                        id=document.id,
                        title=document.title,
                        source_path=document.source_path,
                        content_hash=document.content_hash,
                    )
                )
            else:
                existing.title = document.title
                existing.source_path = document.source_path
                existing.content_hash = document.content_hash
                self._session.execute(
                    delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id)
                )
            self._session.flush()
            self._session.add_all(
                KnowledgeChunk(
                    id=c.id,
                    document_id=c.document_id,
                    chunk_index=c.chunk_index,
                    content=c.content,
                    section=c.section,
                    embedding=c.embedding,
                    chunk_metadata=c.metadata,
                )
                for c in chunks
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def delete_document(self, document_id: str) -> None:
        self._session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
        self._session.commit()

    def search(self, embedding: list[float], top_k: int) -> list[RetrievedChunk]:
        distance = KnowledgeChunk.embedding.cosine_distance(embedding).label("distance")
        stmt = (
            select(KnowledgeChunk, KnowledgeDocument.title, KnowledgeDocument.source_path, distance)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .order_by(distance)
            .limit(top_k)
        )
        return [
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                source_path=source_path,
                section=chunk.section,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=1.0 - float(dist),
            )
            for chunk, title, source_path, dist in self._session.execute(stmt).all()
        ]


def _order_record(order: Order) -> OrderRecord:
    return OrderRecord(
        order_id=order.order_id,
        customer_id=order.customer_id,
        status=order.status,
        created_at=order.created_at,
        estimated_delivery=order.estimated_delivery,
        tracking_number=order.tracking_number,
        items=[OrderItem.model_validate(i) for i in order.items],
    )


class SqlOrderRepository:
    def __init__(self, session: Session):
        self._session = session

    def get(self, order_id: str) -> OrderRecord | None:
        order = self._session.get(Order, order_id)
        return _order_record(order) if order else None


def _ticket_record(ticket: SupportTicket) -> TicketRecord:
    return TicketRecord(
        id=ticket.id,
        customer_id=ticket.customer_id,
        order_id=ticket.order_id,
        request_type=RequestType(ticket.request_type),
        reason=ticket.reason,
        status=TicketStatus(ticket.status),
        summary=ticket.summary,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


class SqlTicketRepository:
    def __init__(self, session: Session):
        self._session = session

    def create(self, ticket: TicketRecord) -> TicketRecord:
        row = SupportTicket(
            id=ticket.id,
            customer_id=ticket.customer_id,
            order_id=ticket.order_id,
            request_type=ticket.request_type.value,
            reason=ticket.reason,
            status=ticket.status.value,
            summary=ticket.summary,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
        )
        try:
            self._session.add(row)
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return _ticket_record(row)

    def get(self, ticket_id: str) -> TicketRecord | None:
        ticket = self._session.get(SupportTicket, ticket_id)
        return _ticket_record(ticket) if ticket else None
