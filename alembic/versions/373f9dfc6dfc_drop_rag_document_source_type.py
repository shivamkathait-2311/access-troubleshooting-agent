"""drop rag_document source_type

The OpenIAM docs auto-crawl was removed — the RAG knowledge base is
upload-only now, so the crawl-vs-upload `source_type` distinction on
rag_documents has no remaining reason to exist (every row would read
'upload').

Revision ID: 373f9dfc6dfc
Revises: 2653374f8e2e
Create Date: 2026-07-08

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "373f9dfc6dfc"
down_revision: str | None = "2653374f8e2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("rag_documents", "source_type")


def downgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("source_type", sa.String(32), nullable=False, server_default="crawl"),
    )
