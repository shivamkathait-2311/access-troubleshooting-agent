from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.core.logging import logger_adapter
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.outcome_policy import resolve_outcome
from app.orchestrator.steps import (
    step1_system_availability,
    step2_account_status,
    step3_auth_events,
    step4_authorization,
)
from app.orchestrator.verdicts import (
    PASSWORD_RESET_ELIGIBLE_CAUSES,
    DiagnosticRunResult,
    FunnelStep,
    Outcome,
    VerdictResult,
    VerdictStatus,
)

# Fixed order — every run walks the same pipeline, stopping at the first
# non-PASS verdict (see run()). Step 5 (path/infrastructure) is deferred to
# a later phase — its module stays in app/orchestrator/steps/ unimplemented,
# simply not walked here yet.
_STEP_MODULES = (
    step1_system_availability,
    step2_account_status,
    step3_auth_events,
    step4_authorization,
)
_STEP_NAMES = (
    FunnelStep.SYSTEM_AVAILABILITY,
    FunnelStep.ACCOUNT_STATUS,
    FunnelStep.AUTH_EVENTS,
    FunnelStep.AUTHORIZATION,
)


class DiagnosticOrchestrator:
    """Deterministic state machine — never an LLM. Owns the fixed step
    order and the fail-closed rule: any step error or timeout becomes an
    INCONCLUSIVE verdict, never a raw exception, and the run escalates. This
    is the only component allowed to hand off into app/remediation/.
    """

    async def run(self, ctx: DiagnosticContext) -> DiagnosticRunResult:
        for step_module, step_name in zip(_STEP_MODULES, _STEP_NAMES, strict=True):
            verdict = await self._run_step_fail_closed(step_module.run, ctx, step_name)
            ctx.verdicts.append(verdict)
            if verdict.status != VerdictStatus.PASS_:
                # First FAIL with a known cause, or any error/timeout
                # (INCONCLUSIVE) — stop the funnel here.
                break

        return self._finalize(ctx)

    async def _run_step_fail_closed(
        self,
        step_fn: Callable[[DiagnosticContext], Awaitable[VerdictResult]],
        ctx: DiagnosticContext,
        step_name: FunnelStep,
    ) -> VerdictResult:
        try:
            return await step_fn(ctx)
        except Exception as exc:  # noqa: BLE001 — fail-closed by design
            logger_adapter.error(
                "Diagnostic step failed; converting to INCONCLUSIVE",
                correlation_id=ctx.correlation_id,
                step=step_name.value,
                error=str(exc),
            )
            return VerdictResult(
                step=step_name,
                status=VerdictStatus.INCONCLUSIVE,
                cause_code="step_error",
                evaluated_at=datetime.now(UTC),
            )

    def _finalize(self, ctx: DiagnosticContext) -> DiagnosticRunResult:
        last = ctx.verdicts[-1]
        outcome = resolve_outcome(last.step, last.status, last.cause_code)
        reset_eligible = (last.step, last.cause_code or "") in PASSWORD_RESET_ELIGIBLE_CAUSES

        return DiagnosticRunResult(
            correlation_id=ctx.correlation_id,
            step_verdicts=ctx.verdicts,
            outcome=outcome,
            escalated=outcome == Outcome.ESCALATION,
            password_reset_url=ctx.subject_password_reset_url if reset_eligible else None,
        )
