"""HashiCorp Vault client wrapper for short-lived, per-connector credentials.

Every connector gets its own read-only service-account credential; the
remediation engine gets a separate write-capable credential loaded only
post-approval (see app/remediation/executor.py). Nothing in this project
should ever read a static secret from config/env for connector or
remediation auth — everything routes through this module so leases,
rotation, and revocation are centralized and auditable.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LeasedCredential:
    """A short-lived credential fetched from Vault."""

    value: str
    lease_id: str
    lease_duration_seconds: int


class VaultClient:
    """Thin async wrapper around hvac for short-lived credential leases."""

    def __init__(self, addr: str, role: str):
        self.addr = addr
        self.role = role

    async def get_connector_credential(self, connector_id: str) -> LeasedCredential:
        """Fetch a read-only credential scoped to one connector's secret path."""
        raise NotImplementedError

    async def get_remediation_credential(self) -> LeasedCredential:
        """Fetch the separate write-capable remediation credential.

        Callers must only invoke this post-approval (see
        app/remediation/executor.py) and must never cache the returned
        value beyond the lease duration.
        """
        raise NotImplementedError

    async def revoke(self, lease_id: str) -> None:
        raise NotImplementedError
