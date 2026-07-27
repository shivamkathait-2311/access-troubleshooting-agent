from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditQueryFilters(BaseModel):
    """Row-level-security-scoped query filters — app/audit/service.py applies
    the requester's visibility tier on top of whatever is passed here; a
    self-service user can never widen this beyond their own subject."""

    correlation_id: str | None = None
    subject_sub: str | None = None
    event_type: str | None = None


class AuditEventResponse(BaseModel):
    id: str
    correlation_id: str
    requester_sub: str
    diagnostic_subject_sub: str
    event_type: str
    visibility_tier: str
    payload: dict[str, Any]
    occurred_at: datetime
