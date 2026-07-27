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


class PostgresGrantsConnector(ConnectorSPI):
    """Reads role/grant metadata from a target Postgres instance's catalog
    views using a read-only DB role (SELECT on catalog views only — never
    the application's own operational database)."""

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
