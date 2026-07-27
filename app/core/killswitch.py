"""Agent-wide kill switch.

When engaged, the orchestrator must refuse to start new diagnostic runs
entirely (raise KillSwitchEngagedError before any connector call is made).
This is the coarsest-grained safety control in the system — see
app/remediation/killswitch.py for the remediation-only switch that can be
engaged independently while diagnostics keep running.

Phase 0: backed by a Settings flag (env var flip + restart). A later phase
should back this with a fast, centrally-toggleable store (e.g. Redis) so it
can be engaged without a redeploy.
"""

from app.core.config import settings


def is_agent_killed() -> bool:
    return settings.AGENT_KILL_SWITCH_ENABLED


def assert_agent_not_killed() -> None:
    from app.core.exceptions import KillSwitchEngagedError

    if is_agent_killed():
        raise KillSwitchEngagedError("Agent kill switch is engaged; no new diagnostic runs.")
