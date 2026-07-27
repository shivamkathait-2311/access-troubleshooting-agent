from datetime import timedelta

from app.connectors.base import ConnectorSPI
from app.connectors.types import (
    AuthEvent,
    AvailabilityResult,
    EffectivePermission,
    PermissionAuditEvent,
    RequiredPermission,
    UserStatusResult,
)


class GenericRestConnector(ConnectorSPI):
    """For systems with a simple health/status REST API. Field mappings
    (which JSON path is the status, which is the failure reason, etc.) come
    entirely from the system's policy YAML `connector.config` block — no
    code changes needed to onboard a new "REST-shaped" system."""

    async def resolve_subject_sub(self, login_id: str) -> str | None:
        raise NotImplementedError

    async def check_availability(self, subject_sub: str) -> AvailabilityResult:
        raise NotImplementedError

    async def get_user_status(self, subject_sub: str) -> UserStatusResult:
        raise NotImplementedError

    async def get_auth_events(self, subject_sub: str, time_window: timedelta) -> list[AuthEvent]:
        raise NotImplementedError

    async def get_effective_permissions(
        self, subject_sub: str, resource: str
    ) -> list[EffectivePermission]:
        raise NotImplementedError

    async def get_required_permissions(self, resource: str) -> list[RequiredPermission]:
        raise NotImplementedError

    async def get_permission_audit_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[PermissionAuditEvent]:
        raise NotImplementedError
