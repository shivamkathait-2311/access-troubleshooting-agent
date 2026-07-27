from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AvailabilityStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


class AvailabilityResult(BaseModel):
    status: AvailabilityStatus
    detail: str | None = None
    checked_at: datetime


class AccountStatus(StrEnum):
    ACTIVE = "active"
    LOCKED = "locked"
    DISABLED = "disabled"
    PASSWORD_EXPIRED = "password_expired"
    DEPROVISIONED = "deprovisioned"
    NOT_FOUND = "not_found"


class UserStatusResult(BaseModel):
    status: AccountStatus
    detail: str | None = None
    password_reset_url: str | None = Field(
        default=None,
        description=(
            "A connector-supplied, ready-to-use self-service password reset "
            "link for this account, if the connector can build one — opaque "
            "to everything downstream (see app/orchestrator/verdict_messages.py)."
        ),
    )


class AuthEvent(BaseModel):
    """One login/auth attempt, already identity-normalized by the connector
    (see app/logquery/types.py for the shared normalization vocabulary)."""

    timestamp: datetime
    success: bool
    failure_reason: str | None = None
    source_ip: str | None = None


class EffectivePermission(BaseModel):
    """A role/group/grant the subject actually holds on the target system."""

    kind: str  # e.g. "role", "group", "db_grant"
    name: str
    source: str | None = None
    end_date: datetime | None = Field(
        default=None,
        description=(
            "When this specific grant expires, if it has an expiry "
            "(OpenIAM's accessRightEndDate) — None means no expiry set. A "
            "grant whose end_date has passed no longer counts as held."
        ),
    )


class RequiredPermission(BaseModel):
    """A role/group/grant the target resource demands."""

    kind: str
    name: str


class PermissionAuditEvent(BaseModel):
    """One audit-log entry relevant to a role/group grant, its removal, or
    its provisioning/sync status. Interpretation (revoked vs. stale-sync
    advisory) happens in the orchestrator, not here — this is a thin,
    faithful mapping of the raw event."""

    action: str
    result: str | None = None  # raw, uninterpreted — success/failure values not yet confirmed
    target_names: list[str] = Field(default_factory=list)
    actor: str | None = None
    occurred_at: datetime
