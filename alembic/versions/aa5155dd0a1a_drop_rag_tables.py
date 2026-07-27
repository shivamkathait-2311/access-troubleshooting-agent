"""drop rag tables

The RAG Q&A subsystem (upload + query) was removed entirely in favor of the
real diagnostic funnel — see app/orchestrator/. Drops every RAG table and
the pgvector extension. `downgrade()` recreates the schema via raw SQL
(not the `pgvector.sqlalchemy.Vector` column type) since the `pgvector`
Python dependency was removed along with the feature.

Revision ID: aa5155dd0a1a
Revises: 373f9dfc6dfc
Create Date: 2026-07-09

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aa5155dd0a1a"
down_revision: str | None = "373f9dfc6dfc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RAG_VECTOR_DIMENSION = 1024


def upgrade() -> None:
    op.drop_table("rag_messages")
    op.drop_table("rag_conversations")
    op.drop_table("rag_chunks")
    op.drop_table("rag_documents")
    op.execute("DROP EXTENSION IF EXISTS vector")


def downgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE rag_documents (
            id UUID PRIMARY KEY,
            source_url VARCHAR(512) NOT NULL,
            title VARCHAR(512) NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            last_crawled_at TIMESTAMPTZ DEFAULT now(),
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.create_index(
        "ix_rag_documents_source_url", "rag_documents", ["source_url"], unique=True
    )

    op.execute(
        f"""
        CREATE TABLE rag_chunks (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding VECTOR({RAG_VECTOR_DIMENSION}) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.create_index("ix_rag_chunks_document_id", "rag_chunks", ["document_id"])
    op.execute(
        "CREATE INDEX ix_rag_chunks_embedding_hnsw ON rag_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.execute(
        """
        CREATE TABLE rag_conversations (
            id UUID PRIMARY KEY,
            client_identifier VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            last_active_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE rag_messages (
            id UUID PRIMARY KEY,
            conversation_id UUID NOT NULL REFERENCES rag_conversations(id) ON DELETE CASCADE,
            role VARCHAR(16) NOT NULL,
            content TEXT NOT NULL,
            citations JSON,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.create_index("ix_rag_messages_conversation_id", "rag_messages", ["conversation_id"])
