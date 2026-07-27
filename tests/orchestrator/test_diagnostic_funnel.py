"""The 4 named Phase 1 scenarios from the design doc, run against a fake
connector — proves the funnel's stop-at-first-fail behavior and the
outcome mapping are correct independent of any real system being reachable.
"""

from datetime import UTC, datetime, timedelta

from app.connectors.base import ConnectorSPI
from app.connectors.types import (
    AccountStatus,
    AuthEvent,
    AvailabilityResult,
    AvailabilityStatus,
    EffectivePermission,
    PermissionAuditEvent,
    RequiredPermission,
    UserStatusResult,
)
from app.core.security import Principal
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.state_machine import DiagnosticOrchestrator
from app.orchestrator.verdicts import FunnelStep, Outcome, VerdictStatus
from app.schemas.intake import ComplaintCategory, DiagnosticRequest


class FakeConnector(ConnectorSPI):
    """Every method's return value is configured directly at construction —
    no real network/API calls."""

    def __init__(
        self,
        availability: AvailabilityResult | None = None,
        user_status: UserStatusResult | None = None,
        auth_events: list[AuthEvent] | None = None,
        effective_permissions: list[EffectivePermission] | None = None,
        required_permissions: list[RequiredPermission] | None = None,
        permission_audit_events: list[PermissionAuditEvent] | None = None,
    ):
        super().__init__("fake", {})
        self._availability = availability or AvailabilityResult(
            status=AvailabilityStatus.UP, checked_at=datetime.now(UTC)
        )
        self._user_status = user_status or UserStatusResult(status=AccountStatus.ACTIVE)
        self._auth_events = auth_events if auth_events is not None else []
        self._effective_permissions = (
            effective_permissions if effective_permissions is not None else []
        )
        self._required_permissions = (
            required_permissions if required_permissions is not None else []
        )
        self._permission_audit_events = (
            permission_audit_events if permission_audit_events is not None else []
        )

    async def resolve_subject_sub(self, login_id: str) -> str | None:
        raise NotImplementedError

    async def check_availability(self, subject_sub: str) -> AvailabilityResult:
        return self._availability

    async def get_user_status(self, subject_sub: str) -> UserStatusResult:
        return self._user_status

    async def get_auth_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[AuthEvent]:
        return self._auth_events

    async def get_effective_permissions(
        self, subject_sub: str, resource: str
    ) -> list[EffectivePermission]:
        return self._effective_permissions

    async def get_required_permissions(self, resource: str) -> list[RequiredPermission]:
        return self._required_permissions

    async def get_permission_audit_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[PermissionAuditEvent]:
        return self._permission_audit_events


def _make_context(connector: ConnectorSPI) -> DiagnosticContext:
    request = DiagnosticRequest(
        correlation_id="test-correlation-id",
        requester_sub="test-user",
        subject_sub="test-user",
        system_id="test-system",
        complaint_category=ComplaintCategory.LOGIN_FAILURE,
        free_text_summary="test complaint",
    )
    return DiagnosticContext(
        request=request,
        principal=Principal(sub="test-user"),
        connector=connector,
    )


async def test_locked_account_is_self_service_fix() -> None:
    connector = FakeConnector(
        user_status=UserStatusResult(
            status=AccountStatus.LOCKED,
            detail="too many attempts",
            password_reset_url="https://example.com/reset",
        ),
    )
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert [v.step for v in result.step_verdicts] == [
        FunnelStep.SYSTEM_AVAILABILITY,
        FunnelStep.ACCOUNT_STATUS,
    ]
    assert result.step_verdicts[-1].status == VerdictStatus.FAIL
    assert result.step_verdicts[-1].cause_code == "locked"
    assert result.outcome == Outcome.SELF_SERVICE_FIX
    assert result.escalated is False
    # Not a reset-eligible cause — unlocking is admin-only per OpenIAM's
    # docs, so the connector-supplied link is never surfaced here.
    assert result.password_reset_url is None


async def test_active_account_does_not_leak_reset_url() -> None:
    """Even when the connector has a reset link on file for the account
    (e.g. OpenIAM returns a login/principal), it must not be surfaced when
    the diagnosed outcome has nothing to do with a password reset — here
    every step passes and the funnel escalates for an unknown cause."""
    connector = FakeConnector(
        user_status=UserStatusResult(
            status=AccountStatus.ACTIVE,
            password_reset_url="https://example.com/reset",
        ),
    )
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert result.outcome == Outcome.ESCALATION
    assert result.password_reset_url is None


async def test_expired_password_is_self_service_fix() -> None:
    connector = FakeConnector(user_status=UserStatusResult(status=AccountStatus.PASSWORD_EXPIRED))
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert result.step_verdicts[-1].step == FunnelStep.ACCOUNT_STATUS
    assert result.step_verdicts[-1].cause_code == "password_expired"
    assert result.outcome == Outcome.SELF_SERVICE_FIX
    assert result.escalated is False


async def test_missing_role_is_access_gap() -> None:
    connector = FakeConnector(
        required_permissions=[RequiredPermission(kind="role", name="app-dashboard-viewer")],
        effective_permissions=[],
    )
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert [v.step for v in result.step_verdicts] == [
        FunnelStep.SYSTEM_AVAILABILITY,
        FunnelStep.ACCOUNT_STATUS,
        FunnelStep.AUTH_EVENTS,
        FunnelStep.AUTHORIZATION,
    ]
    assert result.step_verdicts[-1].status == VerdictStatus.FAIL
    assert result.step_verdicts[-1].cause_code == "missing_role"
    assert result.outcome == Outcome.ACCESS_GAP
    assert result.escalated is False


async def test_expired_access_is_access_gap() -> None:
    connector = FakeConnector(
        required_permissions=[RequiredPermission(kind="role", name="app-dashboard-viewer")],
        effective_permissions=[
            EffectivePermission(
                kind="role",
                name="app-dashboard-viewer",
                end_date=datetime.now(UTC) - timedelta(days=1),
            )
        ],
    )
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert result.step_verdicts[-1].step == FunnelStep.AUTHORIZATION
    assert result.step_verdicts[-1].cause_code == "access_expired"
    assert result.outcome == Outcome.ACCESS_GAP
    assert result.escalated is False


async def test_revoked_access_is_escalation() -> None:
    connector = FakeConnector(
        required_permissions=[RequiredPermission(kind="role", name="app-dashboard-viewer")],
        effective_permissions=[],
        permission_audit_events=[
            PermissionAuditEvent(
                action="DELETE_USER_FROM_ROLE",
                result="SUCCESS",
                target_names=["app-dashboard-viewer"],
                actor="admin.jane",
                occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            )
        ],
    )
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert result.step_verdicts[-1].step == FunnelStep.AUTHORIZATION
    assert result.step_verdicts[-1].cause_code == "access_revoked"
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True


async def test_outage_is_escalation() -> None:
    connector = FakeConnector(
        availability=AvailabilityResult(
            status=AvailabilityStatus.DOWN, checked_at=datetime.now(UTC)
        )
    )
    result = await DiagnosticOrchestrator().run(_make_context(connector))

    assert len(result.step_verdicts) == 1
    assert result.step_verdicts[0].step == FunnelStep.SYSTEM_AVAILABILITY
    assert result.step_verdicts[0].cause_code == "system_down"
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True
