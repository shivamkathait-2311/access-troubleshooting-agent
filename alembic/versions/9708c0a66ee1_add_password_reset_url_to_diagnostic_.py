"""add password_reset_url to diagnostic_runs

Revision ID: 9708c0a66ee1
Revises: a8ea2cc3213a
Create Date: 2026-07-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9708c0a66ee1"
down_revision: str | None = "a8ea2cc3213a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_runs", sa.Column("password_reset_url", sa.String(2048), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("diagnostic_runs", "password_reset_url")
