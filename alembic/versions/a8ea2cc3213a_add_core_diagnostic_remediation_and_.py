"""add core diagnostic, remediation, and audit tables

The original Phase 0 scaffold modeled these tables in SQLAlchemy
(app/models/diagnostic_request.py, diagnostic_run.py, remediation_action.py,
audit_event.py) but a migration for them was never written — only the
RAG-related migrations exist so far. This fills that gap so `POST /intake`,
`POST /diagnostics/{id}/run`, remediation, and `GET /audit` have real tables
to persist to.

Revision ID: a8ea2cc3213a
Revises: aa5155dd0a1a
Create Date: 2026-07-09

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8ea2cc3213a"
down_revision: str | None = "aa5155dd0a1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("requester_sub", sa.String(255), nullable=False),
        sa.Column("diagnostic_subject_sub", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("visibility_tier", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        schema="audit",
    )
    op.create_index(
        "ix_audit_audit_events_correlation_id",
        "audit_events",
        ["correlation_id"],
        schema="audit",
    )

    op.create_table(
        "diagnostic_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("requester_sub", sa.String(255), nullable=False),
        sa.Column("subject_sub", sa.String(255), nullable=False),
        sa.Column("system_id", sa.String(128), nullable=False),
        sa.Column("raw_complaint_text", sa.String(), nullable=False),
        sa.Column("parsed_draft", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_diagnostic_requests_correlation_id", "diagnostic_requests", ["correlation_id"]
    )

    op.create_table(
        "diagnostic_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "request_id", sa.Uuid(), sa.ForeignKey("diagnostic_requests.id"), nullable=False
        ),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("step_verdicts", sa.JSON(), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_diagnostic_runs_correlation_id", "diagnostic_runs", ["correlation_id"])

    op.create_table(
        "remediation_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "diagnostic_run_id", sa.Uuid(), sa.ForeignKey("diagnostic_runs.id"), nullable=False
        ),
        sa.Column("playbook_id", sa.String(128), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("rollback_data", sa.JSON(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("remediation_actions")
    op.drop_index("ix_diagnostic_runs_correlation_id", table_name="diagnostic_runs")
    op.drop_table("diagnostic_runs")
    op.drop_index("ix_diagnostic_requests_correlation_id", table_name="diagnostic_requests")
    op.drop_table("diagnostic_requests")
    op.drop_index(
        "ix_audit_audit_events_correlation_id", table_name="audit_events", schema="audit"
    )
    op.drop_table("audit_events", schema="audit")
    op.execute("DROP SCHEMA IF EXISTS audit")
