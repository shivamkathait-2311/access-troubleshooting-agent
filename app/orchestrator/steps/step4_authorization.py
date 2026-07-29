from datetime import UTC, datetime, timedelta

from app.connectors.types import PermissionAuditEvent
from app.orchestrator.audit_action_taxonomy import (
    REVOKE_ACTIONS as _REVOKE_ACTIONS,
)
from app.orchestrator.audit_action_taxonomy import (
    SYNC_ADVISORY_ACTIONS as _SYNC_ADVISORY_ACTIONS,
)
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import FunnelStep, VerdictResult, VerdictStatus

_AUDIT_LOOKBACK = timedelta(days=365)

# Most specific/actionable-explanation first — one cause_code per verdict,
# so when several required names are missing for different reasons, the
# overall verdict reports whichever is most specific.
_CAUSE_PRIORITY = {"access_revoked": 0, "access_expired": 1, "missing_role": 2}


def _classify_missing(name: str, expired_names: set[str], revoked_names: set[str]) -> str:
    if name in revoked_names:
        return "access_revoked"
    if name in expired_names:
        return "access_expired"
    return "missing_role"


def _describe_missing(
    name: str,
    cause: str,
    expired_end_dates: dict[str, datetime],
    revoke_events: dict[str, PermissionAuditEvent],
) -> str:
    if cause == "access_revoked":
        event = revoke_events[name]
        return f"'{name}' was revoked on {event.occurred_at.isoformat()}"
    if cause == "access_expired":
        return f"'{name}' access expired on {expired_end_dates[name].isoformat()}"
    return f"'{name}'"


def _sync_advisory_note(sync_events: list[PermissionAuditEvent]) -> str | None:
    if not sync_events:
        return None
    latest = max(sync_events, key=lambda e: e.occurred_at)
    return (
        f"A provisioning/sync event was also recorded (action={latest.action}, "
        f"result={latest.result}, at={latest.occurred_at.isoformat()}) — may be "
        "related; not yet confirmed as a definitive cause."
    )


async def run(ctx: DiagnosticContext) -> VerdictResult:
    """Q: Does the user's effective access satisfy the resource's
    requirement? Distinguishes missing (never granted), access_expired (was
    granted, accessRightEndDate has passed), and access_revoked (was
    granted, an explicit DELETE_USER_FROM_ROLE/GROUP event found) via
    connector.get_effective_permissions() vs. get_required_permissions()
    vs. get_permission_audit_events(). Also surfaces provisioning/
    reconciliation events as an advisory-only note — never gates PASS/FAIL,
    since their success/failure semantics aren't confirmed yet.

    `resource` is one primary resource per system for this phase (see
    SystemPolicy.role_permission_map) — a system with no declared
    requirement for it simply has nothing to check, so this step passes.
    """
    resource = f"{ctx.request.system_id}:default"

    required = await ctx.connector.get_required_permissions(resource)
    if not required:
        return VerdictResult(
            step=FunnelStep.AUTHORIZATION,
            status=VerdictStatus.PASS_,
            source_connector_id=ctx.connector.connector_id,
            evaluated_at=datetime.now(UTC),
        )

    effective = await ctx.connector.get_effective_permissions(ctx.request.subject_sub, resource)
    now = datetime.now(UTC)
    held_names = {p.name for p in effective if p.end_date is None or p.end_date > now}
    expired_end_dates = {
        p.name: p.end_date for p in effective if p.end_date is not None and p.end_date <= now
    }

    missing = [r.name for r in required if r.name not in held_names]

    audit_events = await ctx.connector.get_permission_audit_events(
        ctx.request.subject_sub, _AUDIT_LOOKBACK
    )
    sync_events = [e for e in audit_events if e.action in _SYNC_ADVISORY_ACTIONS]

    if not missing:
        return VerdictResult(
            step=FunnelStep.AUTHORIZATION,
            status=VerdictStatus.PASS_,
            detail=_sync_advisory_note(sync_events),
            source_connector_id=ctx.connector.connector_id,
            evaluated_at=datetime.now(UTC),
        )

    revoke_events: dict[str, PermissionAuditEvent] = {}
    for event in audit_events:
        if event.action not in _REVOKE_ACTIONS:
            continue
        for name in event.target_names:
            existing = revoke_events.get(name)
            if existing is None or event.occurred_at > existing.occurred_at:
                revoke_events[name] = event

    causes = {
        name: _classify_missing(name, set(expired_end_dates), set(revoke_events))
        for name in missing
    }
    cause_code = min(causes.values(), key=_CAUSE_PRIORITY.__getitem__)

    descriptions = [
        _describe_missing(name, causes[name], expired_end_dates, revoke_events)
        for name in missing
    ]
    detail = f"Missing required access: {'; '.join(descriptions)}"
    sync_note = _sync_advisory_note(sync_events)
    if sync_note:
        detail = f"{detail}. {sync_note}"

    return VerdictResult(
        step=FunnelStep.AUTHORIZATION,
        status=VerdictStatus.FAIL,
        cause_code=cause_code,
        detail=detail,
        source_connector_id=ctx.connector.connector_id,
        evaluated_at=datetime.now(UTC),
    )
