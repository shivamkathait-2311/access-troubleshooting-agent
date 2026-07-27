from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class VisibilityTier(StrEnum):
    """Row-level-security tiers, per the design doc's internal permission
    model: self-service user -> helpdesk -> IAM admin."""

    SELF_SERVICE_USER = "self_service_user"
    HELPDESK = "helpdesk"
    IAM_ADMIN = "iam_admin"


class AuditEventType(StrEnum):
    DIAGNOSTIC_REQUEST_RECEIVED = "diagnostic_request_received"
    DIAGNOSTIC_RUN_COMPLETED = "diagnostic_run_completed"
    REMEDIATION_REQUESTED = "remediation_requested"
    REMEDIATION_APPROVED = "remediation_approved"
    REMEDIATION_DENIED = "remediation_denied"
    REMEDIATION_EXECUTED = "remediation_executed"
    ESCALATION_CREATED = "escalation_created"
    KILL_SWITCH_TOGGLED = "kill_switch_toggled"


class AuditEvent(BaseModel):
    """Append-only audit record shape. Mirrors models/audit_event.py.
    `payload` must already be redacted by the caller — this schema does not
    perform redaction itself."""

    correlation_id: str
    requester_sub: str
    diagnostic_subject_sub: str
    event_type: AuditEventType
    visibility_tier: VisibilityTier
    payload: dict[str, Any]
    occurred_at: datetime
