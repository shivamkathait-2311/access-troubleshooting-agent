from datetime import UTC, datetime

from app.connectors.types import AccountStatus
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import FunnelStep, VerdictResult, VerdictStatus


async def run(ctx: DiagnosticContext) -> VerdictResult:
    """Q: Does the account exist and is it active? Catches locked/disabled/
    expired-password/deprovisioned via connector.get_user_status()."""
    result = await ctx.connector.get_user_status(ctx.request.subject_sub)
    ctx.subject_password_reset_url = result.password_reset_url

    status = (
        VerdictStatus.PASS_ if result.status == AccountStatus.ACTIVE else VerdictStatus.FAIL
    )
    return VerdictResult(
        step=FunnelStep.ACCOUNT_STATUS,
        status=status,
        cause_code=None if status == VerdictStatus.PASS_ else result.status.value,
        detail=result.detail,
        source_connector_id=ctx.connector.connector_id,
        evaluated_at=datetime.now(UTC),
    )
