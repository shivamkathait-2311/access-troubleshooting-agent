"""app/orchestrator/agent_tools.py's redaction guarantees and the
zero-argument tool-schema invariant — the LLM diagnostic agent must never
see raw connector `detail` strings, password_reset_url, actor identities,
or raw audit result strings, and must never be able to supply any argument
to any tool (subject_sub/resource/time windows are always closure-bound).
No real network call — driven against the same FakeConnector used by
test_diagnostic_funnel.py."""

import json
from datetime import UTC, datetime, timedelta

from test_diagnostic_funnel import FakeConnector, _make_context

from app.connectors.types import (
    AccountStatus,
    AuthEvent,
    AvailabilityResult,
    AvailabilityStatus,
    EffectivePermission,
    PermissionAuditEvent,
    RequiredPermission,
    UserStatusResult,
)
from app.llm.tool_types import ToolCall
from app.orchestrator.agent_tools import TOOL_TO_STEP, build_agent_tools
from app.orchestrator.verdicts import FunnelStep


async def _call_tool(connector: FakeConnector, tool_name: str) -> str:
    ctx = _make_context(connector)
    _, dispatch = build_agent_tools(ctx)
    return await dispatch(ToolCall(call_id="c1", name=tool_name, arguments={}))


def test_every_tool_has_an_empty_parameter_schema() -> None:
    ctx = _make_context(FakeConnector())
    tool_specs, _ = build_agent_tools(ctx)
    assert len(tool_specs) == 6
    for spec in tool_specs:
        assert spec.parameters_schema == {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }


def test_tool_specs_never_mention_subject_sub() -> None:
    ctx = _make_context(FakeConnector())
    tool_specs, _ = build_agent_tools(ctx)
    serialized = json.dumps([spec.model_dump() for spec in tool_specs])
    assert "subject_sub" not in serialized
    assert "test-user" not in serialized


def test_tool_to_step_covers_every_tool_spec() -> None:
    ctx = _make_context(FakeConnector())
    tool_specs, _ = build_agent_tools(ctx)
    assert {spec.name for spec in tool_specs} == set(TOOL_TO_STEP)


async def test_check_availability_redacted() -> None:
    connector = FakeConnector(
        availability=AvailabilityResult(
            status=AvailabilityStatus.DOWN,
            detail="Managed system(s) not working: AD Powershell Managed System",
            checked_at=datetime.now(UTC),
        )
    )
    content = await _call_tool(connector, "check_availability")
    body = json.loads(content)
    assert body == {"status": "down"}
    assert "AD Powershell" not in content


async def test_get_user_status_redacted_and_sets_reset_url_side_effect() -> None:
    connector = FakeConnector(
        user_status=UserStatusResult(
            status=AccountStatus.LOCKED,
            detail="OpenIAM status=ACTIVE secondaryStatus=LOCKED",
            password_reset_url="https://qa422.openiam.com/idp/auth-select?login=aaa",
        )
    )
    ctx = _make_context(connector)
    _, dispatch = build_agent_tools(ctx)
    content = await dispatch(ToolCall(call_id="c1", name="get_user_status", arguments={}))

    body = json.loads(content)
    assert body == {"status": "locked"}
    assert "secondaryStatus" not in content
    assert "login=aaa" not in content
    # Side effect mirrors step2_account_status.py, for later reset-link use.
    assert ctx.subject_password_reset_url == "https://qa422.openiam.com/idp/auth-select?login=aaa"


async def test_get_auth_events_redacted_and_capped() -> None:
    now = datetime.now(UTC)
    events = [
        AuthEvent(
            timestamp=now - timedelta(minutes=i),
            success=False,
            failure_reason="INCREMENT_FAIL_AUTH_COUNT",
            source_ip="10.0.0.1",
        )
        for i in range(25)
    ]
    connector = FakeConnector(auth_events=events)
    content = await _call_tool(connector, "get_auth_events")

    body = json.loads(content)
    assert len(body["events"]) == 20
    assert all(set(event.keys()) == {"timestamp", "success"} for event in body["events"])
    assert "INCREMENT_FAIL_AUTH_COUNT" not in content
    assert "10.0.0.1" not in content


async def test_get_effective_permissions_redacted_and_expiry_collapsed_to_bool() -> None:
    now = datetime.now(UTC)
    connector = FakeConnector(
        effective_permissions=[
            EffectivePermission(kind="role", name="Super Security Admin", source="OPENIAM"),
            EffectivePermission(
                kind="role",
                name="Stale Role",
                source="OPENIAM",
                end_date=now - timedelta(days=1),
            ),
        ]
    )
    content = await _call_tool(connector, "get_effective_permissions")
    body = json.loads(content)
    assert body == {
        "permissions": [
            {"kind": "role", "name": "Super Security Admin", "expired": False},
            {"kind": "role", "name": "Stale Role", "expired": True},
        ]
    }
    assert "OPENIAM" not in content  # `source` dropped


async def test_get_required_permissions_redacted() -> None:
    connector = FakeConnector(
        required_permissions=[RequiredPermission(kind="role", name="Super Security Admin")]
    )
    content = await _call_tool(connector, "get_required_permissions")
    assert json.loads(content) == {
        "permissions": [{"kind": "role", "name": "Super Security Admin"}]
    }


async def test_get_permission_audit_events_classified_and_redacted() -> None:
    now = datetime.now(UTC)
    connector = FakeConnector(
        permission_audit_events=[
            PermissionAuditEvent(
                action="DELETE_USER_FROM_ROLE",
                result="SUCCESS",
                target_names=["Super Security Admin"],
                actor="admin.jane",
                occurred_at=now,
            ),
            PermissionAuditEvent(
                action="RECONCILE_USER",
                result="SUCCESS",
                target_names=[],
                actor="system",
                occurred_at=now,
            ),
            PermissionAuditEvent(
                action="SOME_UNKNOWN_ACTION",
                result="SUCCESS",
                target_names=[],
                actor="system",
                occurred_at=now,
            ),
        ]
    )
    content = await _call_tool(connector, "get_permission_audit_events")
    body = json.loads(content)
    assert [e["action_kind"] for e in body["events"]] == ["revoke", "sync_advisory", "other"]
    assert "admin.jane" not in content  # actor dropped
    assert "SUCCESS" not in content  # raw result dropped
    assert "DELETE_USER_FROM_ROLE" not in content  # raw action string dropped


async def test_dispatch_raises_on_unknown_tool_name() -> None:
    ctx = _make_context(FakeConnector())
    _, dispatch = build_agent_tools(ctx)
    try:
        await dispatch(ToolCall(call_id="c1", name="not_a_real_tool", arguments={}))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for an unknown tool name")


def test_tool_to_step_matches_funnel_steps() -> None:
    assert set(TOOL_TO_STEP.values()) == {
        FunnelStep.SYSTEM_AVAILABILITY,
        FunnelStep.ACCOUNT_STATUS,
        FunnelStep.AUTH_EVENTS,
        FunnelStep.AUTHORIZATION,
    }
