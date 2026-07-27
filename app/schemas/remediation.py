from pydantic import BaseModel

from app.remediation.tiers import Tier


class RemediationRequest(BaseModel):
    diagnostic_run_id: str
    playbook_id: str


class ApprovalRequest(BaseModel):
    remediation_action_id: str
    approver_sub: str


class RemediationActionResponse(BaseModel):
    id: str
    playbook_id: str
    tier: Tier
    status: str
    approval_id: str | None = None
