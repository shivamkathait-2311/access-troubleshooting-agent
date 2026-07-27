import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DiagnosticRequestModel(Base):
    """A single intake request: raw complaint text, the LLM-parsed draft,
    and the orchestrator-validated final request actually acted upon.

    `subject` is always derived from the validated token's `sub` (or an
    explicit elevated-role override) — never taken verbatim from the LLM
    draft. See app/services/intake_service.py.
    """

    __tablename__ = "diagnostic_requests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    requester_sub: Mapped[str] = mapped_column(String(255))
    subject_sub: Mapped[str] = mapped_column(String(255))
    system_id: Mapped[str] = mapped_column(String(128))
    raw_complaint_text: Mapped[str] = mapped_column(String)
    parsed_draft: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
