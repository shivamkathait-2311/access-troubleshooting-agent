from app.connectors.types import AccountStatus
from app.orchestrator.verdicts import FunnelStep, Outcome, VerdictStatus

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


def resolve_outcome(step: FunnelStep, status: VerdictStatus, cause_code: str | None) -> Outcome:
    """The single source of truth for "given this verdict, what should
    happen next" — shared by both DiagnosticOrchestrator (state_machine.py)
    and LLMDiagnosticOrchestrator (agent_loop.py), so the two orchestrators
    can never silently diverge on this safety-relevant policy decision.
    """
    if status == VerdictStatus.INCONCLUSIVE:
        return Outcome.ESCALATION
    if status != VerdictStatus.FAIL:
        # PASS — no explanation found for a complaint that's presumably
        # real. Fail closed: escalate rather than tell the user "everything
        # looks fine".
        return Outcome.ESCALATION

    if step == FunnelStep.SYSTEM_AVAILABILITY:
        return Outcome.ESCALATION  # infra issue, never user-actionable
    if step == FunnelStep.ACCOUNT_STATUS:
        return _ACCOUNT_STATUS_OUTCOME.get(cause_code or "", Outcome.ESCALATION)
    if step == FunnelStep.AUTH_EVENTS:
        return Outcome.SELF_SERVICE_FIX
    if step == FunnelStep.AUTHORIZATION:
        return _AUTHORIZATION_OUTCOME.get(cause_code or "", Outcome.ACCESS_GAP)
    return Outcome.ESCALATION  # PATH_INFRASTRUCTURE isn't walked yet
