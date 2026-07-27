"""Direct tests of step4_authorization.run()'s missing/expired/revoked
branching and the advisory sync note — see app/orchestrator/steps/
step4_authorization.py. Uses a minimal FakeConnector exposing only what
this step calls, independent of test_diagnostic_funnel.py's full-funnel
FakeConnector."""

from datetime import UTC, datetime, timedelta

from app.connectors.base import ConnectorSPI
from app.connectors.types import (
    AuthEvent,
    AvailabilityResult,
    EffectivePermission,
    PermissionAuditEvent,
    RequiredPermission,
    UserStatusResult,
)
from app.core.security import Principal
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.steps import step4_authorization
from app.orchestrator.verdicts import VerdictStatus
from app.schemas.intake import ComplaintCategory, DiagnosticRequest


class FakeConnector(ConnectorSPI):
    def __init__(
        self,
        required: list[RequiredPermission],
        effective: list[EffectivePermission] | None = None,
        audit_events: list[PermissionAuditEvent] | None = None,
    ):
        super().__init__("fake", {})
        self._required = required
        self._effective = effective if effective is not None else []
        self._audit_events = audit_events if audit_events is not None else []

    async def resolve_subject_sub(self, login_id: str) -> str | None:
        raise NotImplementedError

    async def check_availability(self, subject_sub: str) -> AvailabilityResult:
        raise NotImplementedError

    async def get_user_status(self, subject_sub: str) -> UserStatusResult:
        raise NotImplementedError

    async def get_auth_events(self, subject_sub: str, time_window: timedelta) -> list[AuthEvent]:
        raise NotImplementedError

    async def get_effective_permissions(
        self, subject_sub: str, resource: str
    ) -> list[EffectivePermission]:
        return self._effective

    async def get_required_permissions(self, resource: str) -> list[RequiredPermission]:
        return self._required

    async def get_permission_audit_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[PermissionAuditEvent]:
        return self._audit_events


def _make_context(connector: ConnectorSPI) -> DiagnosticContext:
    request = DiagnosticRequest(
        correlation_id="test-correlation-id",
        requester_sub="test-user",
        subject_sub="test-user",
        system_id="test-system",
        complaint_category=ComplaintCategory.PERMISSION_DENIED,
        free_text_summary="test complaint",
    )
    return DiagnosticContext(
        request=request,
        principal=Principal(sub="test-user"),
        connector=connector,
    )


async def test_no_required_permissions_passes_trivially() -> None:
    connector = FakeConnector(required=[])
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.PASS_
    assert verdict.cause_code is None


async def test_held_permission_passes() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[EffectivePermission(kind="role", name="Super Security Admin")],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.PASS_


async def test_never_granted_is_missing_role() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[],
        audit_events=[],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.FAIL
    assert verdict.cause_code == "missing_role"
    assert "Super Security Admin" in verdict.detail


async def test_expired_grant_is_access_expired() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[
            EffectivePermission(
                kind="role",
                name="Super Security Admin",
                end_date=datetime.now(UTC) - timedelta(days=1),
            )
        ],
    )
    ctx = _make_context(connector)
    verdict = await step4_authorization.run(ctx)
    assert verdict.status == VerdictStatus.FAIL
    assert verdict.cause_code == "access_expired"
    assert "Super Security Admin" in verdict.detail


async def test_future_end_date_still_counts_as_held() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[
            EffectivePermission(
                kind="role",
                name="Super Security Admin",
                end_date=datetime.now(UTC) + timedelta(days=30),
            )
        ],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.PASS_


async def test_revoked_grant_is_access_revoked() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[],
        audit_events=[
            PermissionAuditEvent(
                action="DELETE_USER_FROM_ROLE",
                result="SUCCESS",
                target_names=["Super Security Admin"],
                actor="admin.jane",
                occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            )
        ],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.FAIL
    assert verdict.cause_code == "access_revoked"
    assert "Super Security Admin" in verdict.detail
    assert "2026-07-15" in verdict.detail
    # actor stays out of the verdict detail's headline framing per the
    # message-layer redaction discipline — but it's fine if present in
    # detail (support-facing); what must never happen is it leaking into
    # build_verdict_message's friendly text, covered in test_verdict_messages.py.


async def test_revoked_takes_priority_over_missing_when_both_present() -> None:
    connector = FakeConnector(
        required=[
            RequiredPermission(kind="role", name="Super Security Admin"),
            RequiredPermission(kind="role", name="Some Other Role"),
        ],
        effective=[],
        audit_events=[
            PermissionAuditEvent(
                action="DELETE_USER_FROM_ROLE",
                result="SUCCESS",
                target_names=["Super Security Admin"],
                actor="admin.jane",
                occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            )
        ],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.cause_code == "access_revoked"
    assert "Super Security Admin" in verdict.detail
    assert "Some Other Role" in verdict.detail


async def test_advisory_sync_note_present_on_fail_without_changing_cause() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[],
        audit_events=[
            PermissionAuditEvent(
                action="PROVISIONING",
                result="FAILED",
                target_names=[],
                actor="system",
                occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            )
        ],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.cause_code == "missing_role"
    assert "provisioning" in verdict.detail.lower()


async def test_advisory_sync_note_present_on_pass() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[EffectivePermission(kind="role", name="Super Security Admin")],
        audit_events=[
            PermissionAuditEvent(
                action="RECONCILIATION_RECORD_FALSE",
                result=None,
                target_names=[],
                actor=None,
                occurred_at=datetime(2026, 7, 15, tzinfo=UTC),
            )
        ],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.PASS_
    assert verdict.detail is not None
    assert "provisioning/sync event" in verdict.detail


async def test_no_advisory_note_when_no_sync_events() -> None:
    connector = FakeConnector(
        required=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective=[EffectivePermission(kind="role", name="Super Security Admin")],
    )
    verdict = await step4_authorization.run(_make_context(connector))
    assert verdict.status == VerdictStatus.PASS_
    assert verdict.detail is None
