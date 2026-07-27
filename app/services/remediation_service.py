import uuid
from typing import Any

from app.core.exceptions import NotFoundError
from app.models.remediation_action import RemediationActionModel
from app.remediation.executor import RemediationExecutor
from app.remediation.tiers import Tier
from app.repositories.remediation_repository import RemediationRepository


class RemediationService:
    """Creates remediation-action records and delegates execution to
    RemediationExecutor, which owns all the tier/approval/kill-switch
    gating (see app/remediation/executor.py)."""

    def __init__(self, executor: RemediationExecutor, repository: RemediationRepository):
        self.executor = executor
        self.repository = repository

    async def request_remediation(
        self, diagnostic_run_id: uuid.UUID, playbook_id: str, tier: Tier
    ) -> RemediationActionModel:
        action = RemediationActionModel(
            diagnostic_run_id=diagnostic_run_id,
            playbook_id=playbook_id,
            tier=tier.value,
            status="pending",
        )
        return await self.repository.create_action(action)

    async def execute(
        self,
        action_id: uuid.UUID,
        subject_sub: str,
        system_id: str,
        correlation_id: str,
        approval_ticket_id: str | None = None,
    ) -> dict[str, Any]:
        action = await self.repository.get_action(action_id)
        if action is None:
            raise NotFoundError(f"Remediation action {action_id} not found")

        return await self.executor.execute(
            remediation_action_id=str(action.id),
            playbook_id=action.playbook_id,
            subject_sub=subject_sub,
            system_id=system_id,
            correlation_id=correlation_id,
            approval_ticket_id=approval_ticket_id,
        )
