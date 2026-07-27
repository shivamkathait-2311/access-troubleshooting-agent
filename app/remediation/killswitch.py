from app.core.config import settings
from app.core.exceptions import KillSwitchEngagedError
from app.core.killswitch import is_agent_killed


def is_remediation_killed() -> bool:
    """Remediation is disabled if either its own switch is engaged, or the
    agent-wide switch is (agent-wide implies remediation-wide, not the
    other way around)."""
    return is_agent_killed() or settings.REMEDIATION_KILL_SWITCH_ENABLED


def assert_remediation_not_killed() -> None:
    if is_remediation_killed():
        raise KillSwitchEngagedError("Remediation kill switch is engaged.")
