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


class KeycloakConnector(ConnectorSPI):
    """Reference connector implementation against the Keycloak Admin REST
    API, via httpx.AsyncClient. Credential: a read-only Keycloak service
    account with `view-users`/`view-events` roles only (see the project
    design doc's least-privilege requirement) — never an admin credential.
    """

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
