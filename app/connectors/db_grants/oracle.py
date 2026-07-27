from datetime import timedelta

from app.connectors.base import ConnectorSPI
from app.connectors.types import (
    AuthEvent,
    AvailabilityResult,
    EffectivePermission,
    RequiredPermission,
    UserStatusResult,
)

# Not registered in app/connectors/registry.py by default: the `oracledb`
# driver is a heavy, environment-specific dependency kept as the optional
# `oracle` extra in pyproject.toml. Add an import + registry entry once
# someone actually implements this connector and installs the extra.


class OracleGrantsConnector(ConnectorSPI):
    """Reads role/grant metadata from a target Oracle instance using a
    read-only DB account. Requires the `access-troubleshooting-agent[oracle]`
    extra (oracledb / Instant Client)."""

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
