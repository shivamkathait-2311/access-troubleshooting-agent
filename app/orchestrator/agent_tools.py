from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from app.core.config import settings
from app.llm.tool_types import ToolCall, ToolSpec
from app.orchestrator.audit_action_taxonomy import REVOKE_ACTIONS, SYNC_ADVISORY_ACTIONS
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.verdicts import FunnelStep

# Same window step4_authorization.py uses for its own permission-audit
# lookup — duplicated as a plain constant here rather than importing a
# module-private name across files.
_AUDIT_LOOKBACK = timedelta(days=365)

# additionalProperties: false is required by OpenAI's strict function-tool
# mode (see app/llm/client.py's run_tool_turn) — confirmed live.
_EMPTY_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


# ---- Redacted result shapes returned to the model (JSON-serialized) ----
# Every field here is either an enum-like string, a bool, an ISO timestamp,
# or a role/group name — never a raw vendor `detail` string, URL, or actor
# identity. See app/connectors/types.py for the un-redacted originals.


class _AvailabilityToolResult(BaseModel):
    status: str


class _UserStatusToolResult(BaseModel):
    status: str


class _AuthEventToolResult(BaseModel):
    timestamp: str
    success: bool


class _AuthEventsToolResult(BaseModel):
    events: list[_AuthEventToolResult]


class _EffectivePermissionToolResult(BaseModel):
    kind: str
    name: str
    expired: bool


class _EffectivePermissionsToolResult(BaseModel):
    permissions: list[_EffectivePermissionToolResult]


class _RequiredPermissionToolResult(BaseModel):
    kind: str
    name: str


class _RequiredPermissionsToolResult(BaseModel):
    permissions: list[_RequiredPermissionToolResult]


class _PermissionAuditEventToolResult(BaseModel):
    action_kind: Literal["revoke", "sync_advisory", "other"]
    target_names: list[str]
    occurred_at: str


class _PermissionAuditEventsToolResult(BaseModel):
    events: list[_PermissionAuditEventToolResult]


# ---- Tool implementations — each takes the ambient DiagnosticContext via
# closure in build_agent_tools(), never an argument the model supplies. ----


async def _check_availability(ctx: DiagnosticContext) -> str:
    result = await ctx.connector.check_availability(ctx.request.subject_sub)
    return _AvailabilityToolResult(status=result.status.value).model_dump_json()


async def _get_user_status(ctx: DiagnosticContext) -> str:
    result = await ctx.connector.get_user_status(ctx.request.subject_sub)
    # Mirrors step2_account_status.py's side effect — the reset link is
    # opaque, connector-supplied, and never itself sent to the model; it's
    # only picked up later if account_status ends up being the primary
    # finding (see PASSWORD_RESET_ELIGIBLE_CAUSES in agent_loop.py).
    ctx.subject_password_reset_url = result.password_reset_url
    return _UserStatusToolResult(status=result.status.value).model_dump_json()


async def _get_auth_events(ctx: DiagnosticContext) -> str:
    window = timedelta(hours=settings.DIAGNOSTIC_AUTH_EVENTS_LOOKBACK_HOURS)
    events = await ctx.connector.get_auth_events(ctx.request.subject_sub, window)
    latest = sorted(events, key=lambda e: e.timestamp, reverse=True)[:20]
    return _AuthEventsToolResult(
        events=[
            _AuthEventToolResult(timestamp=e.timestamp.isoformat(), success=e.success)
            for e in latest
        ]
    ).model_dump_json()


async def _get_effective_permissions(ctx: DiagnosticContext) -> str:
    resource = f"{ctx.request.system_id}:default"
    permissions = await ctx.connector.get_effective_permissions(ctx.request.subject_sub, resource)
    now = datetime.now(UTC)
    return _EffectivePermissionsToolResult(
        permissions=[
            _EffectivePermissionToolResult(
                kind=p.kind,
                name=p.name,
                expired=p.end_date is not None and p.end_date <= now,
            )
            for p in permissions
        ]
    ).model_dump_json()


async def _get_required_permissions(ctx: DiagnosticContext) -> str:
    resource = f"{ctx.request.system_id}:default"
    permissions = await ctx.connector.get_required_permissions(resource)
    return _RequiredPermissionsToolResult(
        permissions=[
            _RequiredPermissionToolResult(kind=p.kind, name=p.name) for p in permissions
        ]
    ).model_dump_json()


def _classify_action(action: str) -> Literal["revoke", "sync_advisory", "other"]:
    if action in REVOKE_ACTIONS:
        return "revoke"
    if action in SYNC_ADVISORY_ACTIONS:
        return "sync_advisory"
    return "other"


async def _get_permission_audit_events(ctx: DiagnosticContext) -> str:
    events = await ctx.connector.get_permission_audit_events(
        ctx.request.subject_sub, _AUDIT_LOOKBACK
    )
    return _PermissionAuditEventsToolResult(
        events=[
            _PermissionAuditEventToolResult(
                action_kind=_classify_action(e.action),
                target_names=e.target_names,
                occurred_at=e.occurred_at.isoformat(),
            )
            for e in events
        ]
    ).model_dump_json()


_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="check_availability",
        description="Check whether this user's managed system(s) are up and reachable.",
        parameters_schema=_EMPTY_SCHEMA,
    ),
    ToolSpec(
        name="get_user_status",
        description=(
            "Check whether this user's account exists and is active — not "
            "locked, disabled, expired, or deprovisioned."
        ),
        parameters_schema=_EMPTY_SCHEMA,
    ),
    ToolSpec(
        name="get_auth_events",
        description="Check this user's recent login attempts and whether they succeeded or failed.",
        parameters_schema=_EMPTY_SCHEMA,
    ),
    ToolSpec(
        name="get_effective_permissions",
        description=(
            "Check which roles/groups this user actually holds, and "
            "whether any are expired."
        ),
        parameters_schema=_EMPTY_SCHEMA,
    ),
    ToolSpec(
        name="get_required_permissions",
        description="Check which roles/groups are required for this user's request.",
        parameters_schema=_EMPTY_SCHEMA,
    ),
    ToolSpec(
        name="get_permission_audit_events",
        description=(
            "Check recent grant/revoke and provisioning-sync events for "
            "this user's access."
        ),
        parameters_schema=_EMPTY_SCHEMA,
    ),
)

# Which FunnelStep each tool's evidence belongs to — used by agent_loop.py
# to track which steps were actually investigated (for the hallucination
# guard: the model can't name a primary_step it never called a tool for).
TOOL_TO_STEP: dict[str, FunnelStep] = {
    "check_availability": FunnelStep.SYSTEM_AVAILABILITY,
    "get_user_status": FunnelStep.ACCOUNT_STATUS,
    "get_auth_events": FunnelStep.AUTH_EVENTS,
    "get_effective_permissions": FunnelStep.AUTHORIZATION,
    "get_required_permissions": FunnelStep.AUTHORIZATION,
    "get_permission_audit_events": FunnelStep.AUTHORIZATION,
}


def build_agent_tools(
    ctx: DiagnosticContext,
) -> tuple[list[ToolSpec], Callable[[ToolCall], Awaitable[str]]]:
    """The fixed 6-tool list for one diagnostic run, plus a dispatch
    function. Every tool is zero-argument — subject_sub/resource/time
    windows are bound via this closure over ctx, never taken from the
    model (see every ToolSpec.parameters_schema above, always empty)."""
    handlers: dict[str, Callable[[], Awaitable[str]]] = {
        "check_availability": lambda: _check_availability(ctx),
        "get_user_status": lambda: _get_user_status(ctx),
        "get_auth_events": lambda: _get_auth_events(ctx),
        "get_effective_permissions": lambda: _get_effective_permissions(ctx),
        "get_required_permissions": lambda: _get_required_permissions(ctx),
        "get_permission_audit_events": lambda: _get_permission_audit_events(ctx),
    }

    async def dispatch(call: ToolCall) -> str:
        handler = handlers.get(call.name)
        if handler is None:
            raise ValueError(f"Unknown tool requested by model: {call.name!r}")
        return await handler()

    return list(_TOOL_SPECS), dispatch
