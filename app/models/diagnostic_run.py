import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiagnosticRunModel(Base):
    """One execution of the 5-step diagnostic funnel for a request.

    `step_verdicts` stores the ordered list of per-step VerdictResult dicts
    (see app/orchestrator/verdicts.py); `outcome` is the terminal verdict
    type (self_service_fix / remediation_pending / access_gap / escalation).
    """

    __tablename__ = "diagnostic_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagnostic_requests.id"))
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    step_verdicts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    outcome: Mapped[str] = mapped_column(String(64))
    escalated: Mapped[bool] = mapped_column(default=False)
    # Connector-supplied self-service password reset link, if the account
    # status check found one — persisted here so a later /escalate call can
    # reference it without a fresh connector call. See
    # app/orchestrator/verdicts.py::DiagnosticRunResult.password_reset_url.
    password_reset_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
