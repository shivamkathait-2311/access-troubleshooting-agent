from typing import Any

from pydantic import BaseModel, Field


class ConnectorConfig(BaseModel):
    type: str = Field(description="Key into app.connectors.registry's connector type map")
    base_url: str | None = None
    credential_path: str = Field(description="Vault secret path for this connector's credential")
    timeout_seconds: int = 10
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Connector-specific config, e.g. field mappings"
    )


class RolePermissionMapping(BaseModel):
    resource: str
    required_roles: list[str] = Field(default_factory=list)


class ErrorSignature(BaseModel):
    """A known-cause pattern the path/infra step or explanation layer can
    match against (e.g. a proxy log regex → cause_code)."""

    pattern: str
    cause_code: str
    description: str | None = None


class SystemPolicy(BaseModel):
    """The full declarative shape of one system's onboarding config."""

    system_id: str
    display_name: str
    connector: ConnectorConfig
    health_endpoint: str | None = None
    role_permission_map: list[RolePermissionMapping] = Field(default_factory=list)
    error_signatures: list[ErrorSignature] = Field(default_factory=list)
    playbook_ids: list[str] = Field(default_factory=list)
