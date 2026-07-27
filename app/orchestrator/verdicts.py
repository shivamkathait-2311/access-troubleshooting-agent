from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class VerdictStatus(StrEnum):
    PASS_ = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


class FunnelStep(StrEnum):
    SYSTEM_AVAILABILITY = "system_availability"
    ACCOUNT_STATUS = "account_status"
    AUTH_EVENTS = "auth_events"
    AUTHORIZATION = "authorization"
    PATH_INFRASTRUCTURE = "path_infrastructure"


class VerdictResult(BaseModel):
    """The outcome of one funnel step. `cause_code` is a stable, redacted
    identifier (e.g. "account_locked") — never a raw log line or connector
    payload; this is what the LLM explanation layer is allowed to see."""

    step: FunnelStep
    status: VerdictStatus
    cause_code: str | None = None
    detail: str | None = None
    source_connector_id: str | None = None
    evaluated_at: datetime


class Outcome(StrEnum):
    SELF_SERVICE_FIX = "self_service_fix"
    REMEDIATION_PENDING = "remediation_pending"
    ACCESS_GAP = "access_gap"
    ESCALATION = "escalation"


# The only (step, cause) combinations where a password-reset link is
# actually relevant to the diagnosed cause. Shared source of truth for both
# result construction (state_machine.py's _finalize) and message text
# (verdict_messages.py) — a reset link is never useful for e.g. a disabled
# or not_found account, or an all-clear escalation. "locked" is deliberately
# excluded too, for a different reason than those: per OpenIAM's own docs,
# unlocking is an admin-only webconsole action (Reset password -> confirm
# unlock), not something the reset link lets the locked-out user do
# themselves — see _LOCKED_ACCOUNT_MESSAGE in verdict_messages.py.
PASSWORD_RESET_ELIGIBLE_CAUSES: set[tuple[FunnelStep, str]] = {
    (FunnelStep.ACCOUNT_STATUS, "password_expired"),
}


class DiagnosticRunResult(BaseModel):
    """All step verdicts plus the overall outcome. Fully redacted/safe to
    return to the API and to feed to the LLM explanation layer as-is."""

    correlation_id: str
    step_verdicts: list[VerdictResult]
    outcome: Outcome
    escalated: bool
    # Connector-supplied self-service password reset link. Only populated
    # when the diagnosed cause is in PASSWORD_RESET_ELIGIBLE_CAUSES (set by
    # state_machine.py's _finalize) — never returned for outcomes where a
    # reset link isn't actually relevant (e.g. active/disabled/not_found
    # accounts, or an all-clear escalation).
    password_reset_url: str | None = None
