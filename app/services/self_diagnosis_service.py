from app.orchestrator.verdicts import DiagnosticRunResult
from app.policy.store import PolicyStore
from app.services.diagnostic_service import DiagnosticService


class SelfDiagnosisService:
    """Scheduled self-check: runs the diagnostic funnel against the agent's
    own service-account access on every registered system.

    Phase 0: interface only. Phase 1 will synthesize a DiagnosticRequest per
    policy.system_id (requester_sub == subject_sub == the agent's own
    service-account identity) and call DiagnosticService.run_diagnostic for
    each, without going through the LLM intake parser at all.
    """

    def __init__(self, policy_store: PolicyStore, diagnostic_service: DiagnosticService):
        self.policy_store = policy_store
        self.diagnostic_service = diagnostic_service

    async def run_all(self) -> list[DiagnosticRunResult]:
        raise NotImplementedError
