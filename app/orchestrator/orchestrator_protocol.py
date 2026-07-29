from typing import Protocol

from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import DiagnosticRunResult


class DiagnosticOrchestratorProtocol(Protocol):
    """The contract both DiagnosticOrchestrator (state_machine.py, the
    default) and LLMDiagnosticOrchestrator (agent_loop.py, opt-in via
    settings.DIAGNOSTIC_ORCHESTRATOR_MODE) implement. DiagnosticService
    depends only on this — it doesn't know or care which one it was given.
    """

    async def run(self, ctx: DiagnosticContext) -> DiagnosticRunResult: ...
