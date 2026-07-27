from app.orchestrator.verdicts import (
    PASSWORD_RESET_ELIGIBLE_CAUSES,
    DiagnosticRunResult,
    FunnelStep,
    VerdictStatus,
)

_ALL_CLEAR_ESCALATION_MESSAGE = (
    "We checked your account and everything looks correct — the system is up, "
    "your account is active, there's no sign of recent failed logins, and you "
    "have the required access. We couldn't pin down the specific cause "
    "automatically, so we've escalated this to support with the full "
    "diagnostic details. Reference: {correlation_id}."
)

_INCONCLUSIVE_MESSAGE = (
    "We ran into a problem while checking your access, so we couldn't finish "
    "the diagnosis. We've escalated this to support with the full diagnostic "
    "details. Reference: {correlation_id}."
)

_OPENIAM_UNLOCK_DOC_URL = "https://docs.openiam.com/docs-2026.6.2/admin/1-usradmin/13-unlock-account"

# Unlocking is an admin-only action in OpenIAM (confirmed against the docs at
# _OPENIAM_UNLOCK_DOC_URL): an admin logs into the webconsole, finds the user,
# and uses the "Reset password" action, which prompts to confirm the unlock.
# There's no end-user self-service unlock flow — a password_reset_url doesn't
# let the locked-out user do this themselves, so it's deliberately never
# surfaced for this cause (see PASSWORD_RESET_ELIGIBLE_CAUSES).
_LOCKED_ACCOUNT_MESSAGE = (
    "Your account is locked — this happens after too many failed login "
    "attempts (OpenIAM's authentication failure count policy). Unlocking it "
    "requires an admin: contact your IT/helpdesk team and ask them to use "
    "OpenIAM's Reset password action for your account and confirm the "
    "unlock prompt. You'll be asked to set a new password the next time you "
    "log in, and it will sync across every connected system your account "
    f"uses. Full unlock procedure: {_OPENIAM_UNLOCK_DOC_URL}"
)

_STEP_FALLBACK_MESSAGES: dict[FunnelStep, str] = {
    FunnelStep.SYSTEM_AVAILABILITY: (
        "OpenIAM appears to be having an issue right now — this isn't something "
        "you can fix on your end. We've escalated this to support. "
        "Reference: {correlation_id}."
    ),
    FunnelStep.ACCOUNT_STATUS: (
        "There's a problem with your account status. We've escalated this to "
        "support with the full diagnostic details. Reference: {correlation_id}."
    ),
    FunnelStep.AUTH_EVENTS: (
        "Your most recent login attempt failed. Double-check your password and "
        "try again, or reset it if you're not sure. Contact support if this "
        "keeps happening."
    ),
    FunnelStep.AUTHORIZATION: (
        "You don't currently have the access this requires. Submit an access "
        "request for the required role/group and it'll be reviewed."
    ),
    FunnelStep.PATH_INFRASTRUCTURE: (
        "We detected a network/infrastructure issue between you and the "
        "system. We've escalated this to support. Reference: {correlation_id}."
    ),
}

# Overrides for the small, known cause_code sets (account_status's 4 causes,
# authorization's 3 causes). auth_events' cause_code is effectively
# unbounded (OpenIAM's raw audit action string), so it has no per-cause
# entries here — its step fallback above covers every case.
#
# access_expired/access_revoked deliberately don't interpolate the specific
# role/group name, date, or actor into this friendly message — those live
# in the verdict's `detail` field only (see step4_authorization.py), same
# "detail isn't the friendly-message layer" boundary used everywhere else
# in this file.
_CAUSE_MESSAGES: dict[tuple[FunnelStep, str], str] = {
    (FunnelStep.ACCOUNT_STATUS, "locked"): _LOCKED_ACCOUNT_MESSAGE,
    (FunnelStep.ACCOUNT_STATUS, "password_expired"): (
        "Your password has expired for {detail}. Please reset it to regain access."
    ),
    (FunnelStep.ACCOUNT_STATUS, "disabled"): (
        "Your account has been disabled. This requires IT/admin action — "
        "we've escalated your case. Reference: {correlation_id}."
    ),
    (FunnelStep.ACCOUNT_STATUS, "not_found"): (
        "We couldn't find an account for you in OpenIAM — it looks like you "
        "may not have been provisioned access yet. Please submit an access "
        "request."
    ),
    (FunnelStep.ACCOUNT_STATUS, "deprovisioned"): (
        "It looks like your access was deprovisioned and you no longer have "
        "an active account. If you still need this, please submit a new "
        "access request."
    ),
    (FunnelStep.AUTHORIZATION, "missing_role"): (
        "You don't currently have the access this requires. Submit an access "
        "request for the required role/group and it'll be reviewed."
    ),
    (FunnelStep.AUTHORIZATION, "access_expired"): (
        "The access you had for this has expired. Submit a new access "
        "request to get it renewed."
    ),
    (FunnelStep.AUTHORIZATION, "access_revoked"): (
        "Access you previously had was removed. We've escalated this so "
        "support can explain why and help if it should be restored. "
        "Reference: {correlation_id}."
    ),
}


def build_verdict_message(result: DiagnosticRunResult) -> str:
    """A deterministic, templated plain-text message for the run's outcome —
    no LLM call. See app/llm/explanation.py::explain_run for the (currently
    unused) LLM-based alternative, which is out of scope for this phase per
    the design doc's own phasing (Phase 1 = "plain-text verdicts, no LLM";
    the LLM explanation layer is explicitly Phase 3).
    """
    if not result.step_verdicts:
        return _INCONCLUSIVE_MESSAGE.format(correlation_id=result.correlation_id)

    last = result.step_verdicts[-1]

    if last.status == VerdictStatus.INCONCLUSIVE:
        template = _INCONCLUSIVE_MESSAGE
    elif last.status == VerdictStatus.PASS_:
        # Every step ran and passed — matches state_machine.py's own
        # all-pass-still-escalates fail-closed behavior.
        template = _ALL_CLEAR_ESCALATION_MESSAGE
    else:
        cause_key = (last.step, last.cause_code or "")
        template = _CAUSE_MESSAGES.get(cause_key, _STEP_FALLBACK_MESSAGES[last.step])
        reset_eligible = cause_key in PASSWORD_RESET_ELIGIBLE_CAUSES
        message = template.format(correlation_id=result.correlation_id, detail=last.detail or "")
        if reset_eligible and result.password_reset_url:
            message += f" Reset your password here: {result.password_reset_url}"
        return message

    return template.format(correlation_id=result.correlation_id)


# Scenario-specific escalation confirmations — distinct wording from
# build_verdict_message's self-service instructions above, since telling
# someone "escalated for review, but also here's how to fix it yourself"
# reads more naturally than repeating the self-service message verbatim.
_ESCALATION_MESSAGES: dict[FunnelStep, str] = {
    FunnelStep.SYSTEM_AVAILABILITY: (
        "Your case has been escalated as a system outage — our infrastructure "
        "team has been notified. Reference: {correlation_id}."
    ),
    FunnelStep.ACCOUNT_STATUS: (
        "Your case has been escalated for account review. Reference: {correlation_id}."
    ),
    FunnelStep.AUTH_EVENTS: (
        "Your case has been escalated for login review. Reference: {correlation_id}."
    ),
    FunnelStep.AUTHORIZATION: (
        "Your case has been escalated as an access request for the required "
        "role — it'll be reviewed by the resource owner. Reference: {correlation_id}."
    ),
    FunnelStep.PATH_INFRASTRUCTURE: (
        "Your case has been escalated as a network/infrastructure issue. "
        "Reference: {correlation_id}."
    ),
}

_GENERIC_ESCALATION_MESSAGE = (
    "Your case has been escalated to support with the full diagnostic "
    "details. Reference: {correlation_id}."
)


def build_escalation_message(
    last_step: FunnelStep | None,
    cause_code: str | None,
    password_reset_url: str | None,
    correlation_id: str,
) -> str:
    """Deterministic, no-LLM confirmation message for a user-triggered
    escalation (see DiagnosticService.escalate_request). `last_step` and
    `cause_code` are read back from the *original* diagnosis (whichever
    step/cause the funnel stopped at) — no new scenario detection needed;
    the original run already determined it.

    The reset link is only offered for the same small, known-good cases as
    build_verdict_message (locked / password_expired) — not on every
    account_status or auth_events escalation regardless of cause, since a
    reset link doesn't help a disabled/not_found account, and auth_events'
    cause_code is an unbounded raw OpenIAM action string, not necessarily
    password-related at all.
    """
    if last_step is None:
        template = _GENERIC_ESCALATION_MESSAGE
    else:
        template = _ESCALATION_MESSAGES.get(last_step, _GENERIC_ESCALATION_MESSAGE)

    message = template.format(correlation_id=correlation_id)

    cause_key = (last_step, cause_code or "")
    reset_eligible = last_step is not None and cause_key in PASSWORD_RESET_ELIGIBLE_CAUSES
    if reset_eligible and password_reset_url:
        message += (
            " In the meantime, you're welcome to try resetting your password "
            f"yourself here: {password_reset_url}"
        )

    return message
