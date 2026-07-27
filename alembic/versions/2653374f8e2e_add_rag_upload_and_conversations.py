"""add rag upload and conversations

Adds `source_type` to rag_documents (distinguishes an admin-uploaded
document from a crawled OpenIAM doc page; existing rows backfill to
'crawl' via the column's server_default) and two new tables for RAG
conversation memory: rag_conversations, rag_messages.

Revision ID: 2653374f8e2e
Revises: 7db1985defdf
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2653374f8e2e"
down_revision: str | None = "7db1985defdf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("source_type", sa.String(32), nullable=False, server_default="crawl"),
    )

    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_identifier", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "rag_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("rag_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_rag_messages_conversation_id", "rag_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_rag_messages_conversation_id", table_name="rag_messages")
    op.drop_table("rag_messages")
    op.drop_table("rag_conversations")
    op.drop_column("rag_documents", "source_type")
