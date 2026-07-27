import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from app.connectors.base import ConnectorSPI
from app.core.security import Principal
from app.orchestrator.verdicts import VerdictResult
from app.schemas.intake import DiagnosticRequest


@dataclass
class DiagnosticContext:
    """Threaded through every funnel step. Steps read from this and append
    their VerdictResult to `verdicts` — they never call the next step or
    decide the overall outcome; that's state_machine.py's job."""

    request: DiagnosticRequest
    principal: Principal
    connector: ConnectorSPI
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    per_step_timeout: timedelta = field(default=timedelta(seconds=10))
    verdicts: list[VerdictResult] = field(default_factory=list)
    # Set by step2_account_status.py from UserStatusResult.password_reset_url
    # — an opaque, connector-supplied link, not something the orchestrator
    # itself builds. Rides alongside `verdicts` since VerdictResult has no
    # room for it.
    subject_password_reset_url: str | None = None
