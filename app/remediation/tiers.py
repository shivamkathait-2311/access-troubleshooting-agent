from enum import IntEnum


class Tier(IntEnum):
    """Remediation tiers, per the design doc's control matrix."""

    INFORMATIONAL_AUTOMATIC = 0
    """e.g. send a password-reset link. Automatic, no gate."""

    REVERSIBLE_SELF_AFFECTING = 1
    """e.g. unlock own account. Step-up MFA; human-approved initially."""

    ACCESS_CHANGING = 2
    """e.g. add user to a group. Requires resource-owner human approval."""

    PRIVILEGED_OUT_OF_SCOPE = 3
    """e.g. grant admin role. Never executed here — routes to the
    existing access-request workflow instead."""


TIERS_REQUIRING_APPROVAL = frozenset({Tier.ACCESS_CHANGING})
TIERS_OUT_OF_SCOPE = frozenset({Tier.PRIVILEGED_OUT_OF_SCOPE})
