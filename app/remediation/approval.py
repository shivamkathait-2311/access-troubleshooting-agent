from dataclasses import dataclass
from enum import StrEnum


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True)
class ApprovalTicket:
    id: str
    status: ApprovalStatus
    approver_sub: str | None = None


class ApprovalGate:
    """Tier-2 (ACCESS_CHANGING) human-approval gate. Tier-0 actions never
    call this; tier-1 actions use step-up MFA instead (see
    app/dependencies/auth.py), not this gate."""

    async def request_approval(self, remediation_action_id: str) -> ApprovalTicket:
        raise NotImplementedError

    async def check_approval(self, ticket_id: str) -> ApprovalStatus:
        raise NotImplementedError
