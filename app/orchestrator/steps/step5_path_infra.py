from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import VerdictResult


async def run(ctx: DiagnosticContext) -> VerdictResult:
    """Q: Is anything between user and system failing? Catches reverse-proxy
    errors, cert expiry, session timeout — via app/logquery/ adapters
    (proxy log signatures for 401/403/502 patterns). "Not checked" is a
    valid, honest result here if no log source is configured for this
    system — never claim full-stack certainty."""
    raise NotImplementedError
