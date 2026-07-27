import uuid
from typing import Any

from app.audit.service import AuditService
from app.core.exceptions import ApprovalRequiredError, RemediationTierForbiddenError
from app.core.vault import VaultClient
from app.remediation.approval import ApprovalGate, ApprovalStatus
from app.remediation.killswitch import assert_remediation_not_killed
from app.remediation.playbook import PlaybookRegistry, RemediationContext
from app.remediation.tiers import TIERS_OUT_OF_SCOPE, TIERS_REQUIRING_APPROVAL
from app.repositories.remediation_repository import RemediationRepository


class RemediationExecutor:
    """The only component that actually invokes playbook.execute().

    Order of operations: kill-switch check -> tier gate -> (tier 2) approval
    check -> load write-capable credential -> execute -> capture rollback
    data -> write audit record. Every remediation action, approved or
    denied, is recorded via AuditService.
    """

    def __init__(
        self,
        registry: PlaybookRegistry,
        vault: VaultClient,
        approval_gate: ApprovalGate,
        repository: RemediationRepository,
        audit: AuditService,
    ):
        self.registry = registry
        self.vault = vault
        self.approval_gate = approval_gate
        self.repository = repository
        self.audit = audit

    async def execute(
        self,
        *,
        remediation_action_id: str,
        playbook_id: str,
        subject_sub: str,
        system_id: str,
        correlation_id: str,
        approval_ticket_id: str | None = None,
    ) -> dict[str, Any]:
        assert_remediation_not_killed()

        playbook = self.registry.get(playbook_id)

        if playbook.tier in TIERS_OUT_OF_SCOPE:
            raise RemediationTierForbiddenError(
                f"Playbook '{playbook_id}' is tier {playbook.tier}, out of scope; "
                "route to the access-request workflow instead."
            )

        if playbook.tier in TIERS_REQUIRING_APPROVAL:
            if approval_ticket_id is None:
                raise ApprovalRequiredError(f"Playbook '{playbook_id}' requires approval")
            status = await self.approval_gate.check_approval(approval_ticket_id)
            if status != ApprovalStatus.APPROVED:
                raise ApprovalRequiredError(
                    f"Approval ticket '{approval_ticket_id}' is not approved (status={status})"
                )

        credential = await self.vault.get_remediation_credential()
        ctx = RemediationContext(
            subject_sub=subject_sub,
            system_id=system_id,
            write_credential=credential,
            correlation_id=correlation_id,
        )

        rollback_data = await playbook.execute(ctx)
        await self.repository.update_status(uuid.UUID(remediation_action_id), "executed")

        return rollback_data
