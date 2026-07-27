import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RemediationActionModel(Base):
    """A single remediation playbook execution, gated by tier.

    `rollback_data` captures whatever prior-state snapshot the playbook
    needs to support one-click rollback (see app/remediation/playbook.py).
    `approval_id` is set only for tier-2 actions; tier-0/1 actions may have
    it null (automatic / step-up-MFA only, per the tier policy).
    """

    __tablename__ = "remediation_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    diagnostic_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagnostic_runs.id"))
    playbook_id: Mapped[str] = mapped_column(String(128))
    tier: Mapped[int] = mapped_column()
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    rollback_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
