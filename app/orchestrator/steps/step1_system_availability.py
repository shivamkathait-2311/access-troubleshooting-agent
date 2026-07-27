from datetime import UTC, datetime

from app.connectors.types import AvailabilityStatus
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import FunnelStep, VerdictResult, VerdictStatus


async def run(ctx: DiagnosticContext) -> VerdictResult:
    """Q: Are this user's own managed system(s) up? Checks every managed
    system this specific subject has an account on (not a generic
    system-wide ping) via connector.check_availability()."""
    result = await ctx.connector.check_availability(ctx.request.subject_sub)

    status = (
        VerdictStatus.PASS_ if result.status == AvailabilityStatus.UP else VerdictStatus.FAIL
    )
    return VerdictResult(
        step=FunnelStep.SYSTEM_AVAILABILITY,
        status=status,
        cause_code=None if status == VerdictStatus.PASS_ else f"system_{result.status.value}",
        detail=result.detail,
        source_connector_id=ctx.connector.connector_id,
        evaluated_at=datetime.now(UTC),
    )
