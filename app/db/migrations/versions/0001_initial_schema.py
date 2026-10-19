"""Initial schema: knowledge base, synthetic commerce data, support tickets.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source_path", sa.String(500), nullable=False, unique=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(100),
            sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("section", sa.String(300), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("document_id", "chunk_index"),
    )
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])
    # The knowledge base is small (tens of chunks), so exact search is used. Add an HNSW index
    # (vector_cosine_ops) only once the corpus is large enough for approximate search to matter.

    op.create_table(
        "customers",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.String(32), primary_key=True),
        sa.Column("customer_id", sa.String(32), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("estimated_delivery", sa.Date, nullable=True),
        sa.Column("tracking_number", sa.String(64), nullable=True),
        sa.Column("items", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("customer_id", sa.String(32), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("orders.order_id"), nullable=True),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_support_tickets_customer_id", "support_tickets", ["customer_id"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])


def downgrade() -> None:
    op.drop_table("support_tickets")
    op.drop_table("orders")
    op.drop_table("customers")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
