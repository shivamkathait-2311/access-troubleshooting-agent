"""add rag tables

Authored against: RAG_EMBEDDING_PROVIDER=voyage, VOYAGE_EMBEDDING_MODEL=voyage-4,
dimension=1024 (see app/rag/embeddings/dimension.py::RAG_VECTOR_DIMENSION).
Changing the embedding provider/model/dimension after this migration has run
requires a NEW migration to alter the embedding column, plus a full
re-ingestion — never edit this file's literal 1024 in place.

The RAG feature (and its `pgvector` dependency) was later removed entirely —
see the `drop_rag_tables` migration. This file stays as historical record of
an already-applied migration (never edit past migrations), but its
`upgrade`/`downgrade` bodies will not run again, so the `pgvector` import is
made optional rather than reinstating the dependency just to load this module.

Revision ID: 7db1985defdf
Revises:
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pgvector removed along with the RAG feature; see above
    Vector = None  # type: ignore[assignment,misc]

# revision identifiers, used by Alembic.
revision: str = "7db1985defdf"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RAG_VECTOR_DIMENSION = 1024


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "rag_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_url", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "last_crawled_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_rag_documents_source_url", "rag_documents", ["source_url"], unique=True
    )

    op.create_table(
        "rag_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("rag_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("embedding", Vector(RAG_VECTOR_DIMENSION), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rag_chunks_document_id", "rag_chunks", ["document_id"])

    # HNSW over IVFFlat: needs no pre-training/list-count tuning, which
    # matters since this table is empty at migration time.
    op.execute(
        "CREATE INDEX ix_rag_chunks_embedding_hnsw ON rag_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_embedding_hnsw", table_name="rag_chunks")
    op.drop_index("ix_rag_chunks_document_id", table_name="rag_chunks")
    op.drop_table("rag_chunks")
    op.drop_index("ix_rag_documents_source_url", table_name="rag_documents")
    op.drop_table("rag_documents")
    # Extension intentionally left installed — dropping it is a separate,
    # explicit operational decision if no other feature depends on it.
