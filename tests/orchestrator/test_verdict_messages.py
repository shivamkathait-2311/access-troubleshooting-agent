"""build_verdict_message() is deterministic and template-based (no LLM) —
these assert the exact right message is picked for each case, including the
two that aren't reachable via a single FAIL cause_code (all-pass-still-
escalates, and INCONCLUSIVE)."""

from datetime import UTC, datetime

from app.orchestrator.verdict_messages import build_escalation_message, build_verdict_message
from app.orchestrator.verdicts import (
    DiagnosticRunResult,
    FunnelStep,
    Outcome,
    VerdictResult,
    VerdictStatus,
)

_CORRELATION_ID = "corr-123"


def _make_result(
    verdicts: list[VerdictResult],
    outcome: Outcome,
    escalated: bool,
    password_reset_url: str | None = None,
) -> DiagnosticRunResult:
    return DiagnosticRunResult(
        correlation_id=_CORRELATION_ID,
        step_verdicts=verdicts,
        outcome=outcome,
        escalated=escalated,
        password_reset_url=password_reset_url,
    )


def _pass_verdict(step: FunnelStep) -> VerdictResult:
    return VerdictResult(step=step, status=VerdictStatus.PASS_, evaluated_at=datetime.now(UTC))


def _fail_verdict(step: FunnelStep, cause_code: str, detail: str | None = None) -> VerdictResult:
    return VerdictResult(
        step=step,
        status=VerdictStatus.FAIL,
        cause_code=cause_code,
        detail=detail,
        evaluated_at=datetime.now(UTC),
    )


def test_locked_account_message() -> None:
    result = _make_result(
        [
            _pass_verdict(FunnelStep.SYSTEM_AVAILABILITY),
            _fail_verdict(FunnelStep.ACCOUNT_STATUS, "locked"),
        ],
        Outcome.SELF_SERVICE_FIX,
        False,
    )
    message = build_verdict_message(result)
    assert "locked" in message.lower()
    assert "unlock" in message.lower()
    assert "admin" in message.lower()
    assert "docs.openiam.com" in message


def test_password_expired_message_includes_expired_login_detail() -> None:
    result = _make_result(
        [
            _fail_verdict(
                FunnelStep.ACCOUNT_STATUS,
                "password_expired",
                detail="AD Powershell Managed System (expired 2020-01-01)",
            )
        ],
        Outcome.SELF_SERVICE_FIX,
        False,
    )
    message = build_verdict_message(result)
    assert "AD Powershell Managed System" in message
    assert "2020-01-01" in message


def test_deprovisioned_account_message() -> None:
    result = _make_result(
        [_fail_verdict(FunnelStep.ACCOUNT_STATUS, "deprovisioned")],
        Outcome.ACCESS_GAP,
        False,
    )
    message = build_verdict_message(result)
    assert "deprovisioned" in message.lower()
    assert "access request" in message.lower()


def test_missing_role_message() -> None:
    result = _make_result(
        [_fail_verdict(FunnelStep.AUTHORIZATION, "missing_role")],
        Outcome.ACCESS_GAP,
        False,
    )
    message = build_verdict_message(result)
    assert "access request" in message.lower()


def test_access_expired_message() -> None:
    result = _make_result(
        [_fail_verdict(FunnelStep.AUTHORIZATION, "access_expired", detail="'x' expired on ...")],
        Outcome.ACCESS_GAP,
        False,
    )
    message = build_verdict_message(result)
    assert "expired" in message.lower()
    assert "access request" in message.lower()


def test_access_revoked_message_never_leaks_actor_from_detail() -> None:
    # The verdict's `detail` (built by step4_authorization.py) may contain
    # an admin's identity — the friendly message must never surface it,
    # even though both are derived from the same underlying event.
    result = _make_result(
        [
            _fail_verdict(
                FunnelStep.AUTHORIZATION,
                "access_revoked",
                detail="'Super Security Admin' was revoked on 2026-07-15 by admin.jane",
            )
        ],
        Outcome.ESCALATION,
        True,
    )
    message = build_verdict_message(result)
    assert "removed" in message.lower()
    assert "admin.jane" not in message
    assert "Super Security Admin" not in message
    assert _CORRELATION_ID in message


def test_auth_events_failure_uses_step_fallback_regardless_of_raw_cause_code() -> None:
    # cause_code here is an arbitrary OpenIAM audit action string — the
    # message must not depend on knowing it, since that set is unbounded.
    result = _make_result(
        [_fail_verdict(FunnelStep.AUTH_EVENTS, "INCREMENT_FAIL_AUTH_COUNT")],
        Outcome.SELF_SERVICE_FIX,
        False,
    )
    message = build_verdict_message(result)
    assert "login attempt failed" in message.lower()


def test_outage_message_includes_correlation_id() -> None:
    result = _make_result(
        [_fail_verdict(FunnelStep.SYSTEM_AVAILABILITY, "system_down")],
        Outcome.ESCALATION,
        True,
    )
    message = build_verdict_message(result)
    assert _CORRELATION_ID in message


def test_all_pass_still_escalates_with_a_message() -> None:
    result = _make_result(
        [
            _pass_verdict(FunnelStep.SYSTEM_AVAILABILITY),
            _pass_verdict(FunnelStep.ACCOUNT_STATUS),
            _pass_verdict(FunnelStep.AUTH_EVENTS),
            _pass_verdict(FunnelStep.AUTHORIZATION),
        ],
        Outcome.ESCALATION,
        True,
    )
    message = build_verdict_message(result)
    assert "everything looks correct" in message.lower()
    assert _CORRELATION_ID in message


def test_locked_account_message_never_includes_password_reset_link() -> None:
    # Unlocking is admin-only per OpenIAM's docs (a webconsole "Reset
    # password" action, confirmed by an admin) — a connector-supplied
    # password_reset_url must never be surfaced for this cause, whether or
    # not one happens to be available. The message is fixed either way and
    # always points at the OpenIAM unlock-doc reference instead.
    for password_reset_url in (
        None,
        "https://qa422.openiam.com/idp/auth-select?login=test.client22",
    ):
        result = _make_result(
            [_fail_verdict(FunnelStep.ACCOUNT_STATUS, "locked")],
            Outcome.SELF_SERVICE_FIX,
            False,
            password_reset_url=password_reset_url,
        )
        message = build_verdict_message(result)
        assert "auth-select" not in message
        assert "docs.openiam.com" in message


def test_auth_events_failure_never_includes_reset_link() -> None:
    # auth_events' cause_code is an unbounded raw OpenIAM action string, not
    # necessarily password-related — unlike account_status's locked/
    # password_expired, it's never eligible for the reset link, even when
    # one is available.
    result = _make_result(
        [_fail_verdict(FunnelStep.AUTH_EVENTS, "INCREMENT_FAIL_AUTH_COUNT")],
        Outcome.SELF_SERVICE_FIX,
        False,
        password_reset_url="https://qa422.openiam.com/idp/auth-select?login=test.client22",
    )
    message = build_verdict_message(result)
    assert "http" not in message


def test_disabled_account_message_never_includes_reset_link() -> None:
    # A reset link doesn't help a disabled account (needs admin action) —
    # only "locked" and "password_expired" are reset-eligible causes.
    result = _make_result(
        [_fail_verdict(FunnelStep.ACCOUNT_STATUS, "disabled")],
        Outcome.ESCALATION,
        True,
        password_reset_url="https://qa422.openiam.com/idp/auth-select?login=test.client22",
    )
    message = build_verdict_message(result)
    assert "http" not in message


def test_missing_role_message_never_includes_reset_link() -> None:
    # Even if a reset URL happened to be populated (e.g. account_status
    # passed before authorization failed), it's irrelevant here and must
    # not be appended.
    result = _make_result(
        [_fail_verdict(FunnelStep.AUTHORIZATION, "missing_role")],
        Outcome.ACCESS_GAP,
        False,
        password_reset_url="https://qa422.openiam.com/idp/auth-select?login=test.client22",
    )
    message = build_verdict_message(result)
    assert "http" not in message


def test_escalation_message_omits_reset_link_for_locked() -> None:
    # Unlocking is admin-only per OpenIAM's docs — never offer a self-service
    # reset link for this cause, even on a user-triggered escalation.
    url = "https://qa422.openiam.com/idp/auth-select?login=test.client22"
    message = build_escalation_message(FunnelStep.ACCOUNT_STATUS, "locked", url, _CORRELATION_ID)
    assert url not in message


def test_escalation_message_omits_reset_link_for_disabled() -> None:
    url = "https://qa422.openiam.com/idp/auth-select?login=test.client22"
    message = build_escalation_message(FunnelStep.ACCOUNT_STATUS, "disabled", url, _CORRELATION_ID)
    assert "http" not in message


def test_escalation_message_omits_reset_link_for_auth_events() -> None:
    url = "https://qa422.openiam.com/idp/auth-select?login=test.client22"
    message = build_escalation_message(
        FunnelStep.AUTH_EVENTS, "INCREMENT_FAIL_AUTH_COUNT", url, _CORRELATION_ID
    )
    assert "http" not in message


def test_inconclusive_message() -> None:
    result = _make_result(
        [
            VerdictResult(
                step=FunnelStep.SYSTEM_AVAILABILITY,
                status=VerdictStatus.INCONCLUSIVE,
                cause_code="step_error",
                evaluated_at=datetime.now(UTC),
            )
        ],
        Outcome.ESCALATION,
        True,
    )
    message = build_verdict_message(result)
    assert "couldn't finish" in message.lower() or "problem" in message.lower()
    assert _CORRELATION_ID in message
