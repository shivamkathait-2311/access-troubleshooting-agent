from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import FunnelStep, VerdictResult, VerdictStatus


async def run(ctx: DiagnosticContext) -> VerdictResult:
    """Q: Did recent logins succeed or fail, and why? Catches wrong
    password/MFA failure/token-expiry via connector.get_auth_events()."""
    window = timedelta(hours=settings.DIAGNOSTIC_AUTH_EVENTS_LOOKBACK_HOURS)
    events = await ctx.connector.get_auth_events(ctx.request.subject_sub, window)

    if not events:
        # No recent attempts on record — nothing here indicates an auth
        # failure, so this step doesn't block the funnel.
        return VerdictResult(
            step=FunnelStep.AUTH_EVENTS,
            status=VerdictStatus.PASS_,
            source_connector_id=ctx.connector.connector_id,
            evaluated_at=datetime.now(UTC),
        )

    latest = max(events, key=lambda e: e.timestamp)
    status = VerdictStatus.PASS_ if latest.success else VerdictStatus.FAIL
    cause_code = None if status == VerdictStatus.PASS_ else (latest.failure_reason or "auth_failed")
    return VerdictResult(
        step=FunnelStep.AUTH_EVENTS,
        status=status,
        cause_code=cause_code,
        detail=latest.failure_reason,
        source_connector_id=ctx.connector.connector_id,
        evaluated_at=datetime.now(UTC),
    )
