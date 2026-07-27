from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.connectors.types import AccountStatus
from app.core.logging import logger_adapter
from app.orchestrator.context import DiagnosticContext
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

# FAIL outcome mapping: SYSTEM_AVAILABILITY has no per-cause entry because
# it always maps to ESCALATION regardless of cause_code (infra issue, never
# user-actionable) — handled directly in _finalize.
#
# Deliberate MVP-phase decision: LOCKED/PASSWORD_EXPIRED map to
# SELF_SERVICE_FIX, not Outcome.REMEDIATION_PENDING, even though the design
# doc's own example names "account unlock" as the auto-remediation case.
# REMEDIATION_PENDING today would be a dead end — app/remediation/ has zero
# concrete playbooks (no unlock-account-v1 class exists despite being named
# in policy YAML) and its API routes still raise NotImplementedError, so
# classifying this as "pending remediation" would queue an action nothing
# will ever execute. Telling the user to self-service (or contact IT) is
# more honest than a verdict that goes nowhere. Revisit this mapping once a
# real unlock playbook is registered — that's the trigger to flip these two
# entries to Outcome.REMEDIATION_PENDING, not before.
_ACCOUNT_STATUS_OUTCOME = {
    AccountStatus.LOCKED.value: Outcome.SELF_SERVICE_FIX,
    AccountStatus.PASSWORD_EXPIRED.value: Outcome.SELF_SERVICE_FIX,
    AccountStatus.DISABLED.value: Outcome.ESCALATION,
    # Same framing as NOT_FOUND: the user doesn't currently have provisioned
    # access, so "submit a new request" is the right instruction — unlike
    # authorization's access_revoked (ESCALATION), there's no audit event
    # here evidencing an adversarial/for-cause removal to explain.
    AccountStatus.DEPROVISIONED.value: Outcome.ACCESS_GAP,
    AccountStatus.NOT_FOUND.value: Outcome.ACCESS_GAP,
}

# access_revoked maps to ESCALATION rather than ACCESS_GAP: the user
# previously had this access and it was explicitly removed, so "submit a
# new request" is the wrong instruction — a human needs to explain why it
# was revoked (or restore it), not process a from-scratch grant request.
_AUTHORIZATION_OUTCOME = {
    "missing_role": Outcome.ACCESS_GAP,
    "access_expired": Outcome.ACCESS_GAP,
    "access_revoked": Outcome.ESCALATION,
}


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

        if last.status == VerdictStatus.INCONCLUSIVE:
            outcome = Outcome.ESCALATION
        elif last.status == VerdictStatus.FAIL:
            outcome = self._resolve_fail_outcome(last)
        else:
            # Every step ran and every step PASSed — the funnel found no
            # explanation for a complaint that's presumably real. Fail
            # closed: escalate rather than tell the user "everything's fine".
            outcome = Outcome.ESCALATION

        reset_eligible = (last.step, last.cause_code or "") in PASSWORD_RESET_ELIGIBLE_CAUSES

        return DiagnosticRunResult(
            correlation_id=ctx.correlation_id,
            step_verdicts=ctx.verdicts,
            outcome=outcome,
            escalated=outcome == Outcome.ESCALATION,
            password_reset_url=ctx.subject_password_reset_url if reset_eligible else None,
        )

    def _resolve_fail_outcome(self, verdict: VerdictResult) -> Outcome:
        if verdict.step == FunnelStep.SYSTEM_AVAILABILITY:
            return Outcome.ESCALATION  # infra issue, never user-actionable
        if verdict.step == FunnelStep.ACCOUNT_STATUS:
            return _ACCOUNT_STATUS_OUTCOME.get(verdict.cause_code or "", Outcome.ESCALATION)
        if verdict.step == FunnelStep.AUTH_EVENTS:
            return Outcome.SELF_SERVICE_FIX
        if verdict.step == FunnelStep.AUTHORIZATION:
            return _AUTHORIZATION_OUTCOME.get(verdict.cause_code or "", Outcome.ACCESS_GAP)
        return Outcome.ESCALATION  # PATH_INFRASTRUCTURE isn't walked yet
