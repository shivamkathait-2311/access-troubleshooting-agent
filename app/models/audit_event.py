import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base


class AuditEventModel(Base):
    """Append-only audit record. Lives in a dedicated schema
    (settings.AUDIT_DB_SCHEMA) for row-level-security isolation from
    operational tables. There is deliberately no update/delete path anywhere
    in the codebase for this table — see app/audit/service.py, which only
    exposes record() and query().
    """

    __tablename__ = "audit_events"
    __table_args__ = {"schema": settings.AUDIT_DB_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    requester_sub: Mapped[str] = mapped_column(String(255))
    diagnostic_subject_sub: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(64))
    visibility_tier: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
