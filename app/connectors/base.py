from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from app.connectors.types import (
    AuthEvent,
    AvailabilityResult,
    EffectivePermission,
    PermissionAuditEvent,
    RequiredPermission,
    UserStatusResult,
)


class ConnectorSPI(ABC):
    """Standard interface every system connector implements.

    Genericity lives here: onboarding a new system is writing a policy YAML
    (app/policy/) that references an existing connector type, not writing
    new orchestrator code. Every method uses a read-only, Vault-leased
    credential (see app/core/vault.py) — connectors must never hold a
    write-capable credential; that's the remediation engine's job.
    """

    def __init__(self, connector_id: str, config: dict[str, Any]):
        self.connector_id = connector_id
        self.config = config

    @abstractmethod
    async def resolve_subject_sub(self, login_id: str) -> str | None:
        """Resolve a human-readable login/principal (what the user actually
        types to sign in) to the internal subject identifier every other
        method on this interface expects — or None if no match. Used by
        intake to turn a caller-supplied login into a real subject_sub
        before anything else runs."""
        raise NotImplementedError

    @abstractmethod
    async def check_availability(self, subject_sub: str) -> AvailabilityResult:
        """Are this specific user's managed system(s) up? (per-managed-system
        connection-test status, not a generic system-wide probe)"""
        raise NotImplementedError

    @abstractmethod
    async def get_user_status(self, subject_sub: str) -> UserStatusResult:
        """Does the account exist and is it active?"""
        raise NotImplementedError

    @abstractmethod
    async def get_auth_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[AuthEvent]:
        """Recent login attempts and failure reasons."""
        raise NotImplementedError

    @abstractmethod
    async def get_effective_permissions(
        self, subject_sub: str, resource: str
    ) -> list[EffectivePermission]:
        """Roles/groups/grants the subject actually holds."""
        raise NotImplementedError

    @abstractmethod
    async def get_required_permissions(self, resource: str) -> list[RequiredPermission]:
        """Roles/groups/grants the resource demands."""
        raise NotImplementedError

    @abstractmethod
    async def get_permission_audit_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[PermissionAuditEvent]:
        """Grant/revoke and provisioning/sync events for role/group access,
        in the given window."""
        raise NotImplementedError
