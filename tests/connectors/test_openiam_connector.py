"""OpenIAMConnector field-mapping tests — no real network call,
`get_openiam_token_client()` is patched with a fake client whose
`authorized_get` returns a stub response built from a hand-crafted
EditUserModel-shaped body (see app/connectors/openiam/connector.py)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.connectors.openiam.connector import OpenIAMConnector
from app.connectors.types import (
    AccountStatus,
    AvailabilityResult,
    AvailabilityStatus,
    EffectivePermission,
    PermissionAuditEvent,
)


class _StubResponse:
    def __init__(self, body: dict, status_code: int = 200):
        self._body = body
        self.status_code = status_code

    def json(self) -> dict:
        return self._body


def _make_connector() -> OpenIAMConnector:
    return OpenIAMConnector("openiam", {"base_url": "https://qa422.openiam.com/"})


async def _resolve_subject_sub(body: dict, status_code: int = 200) -> str | None:
    connector = _make_connector()
    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(return_value=_StubResponse(body, status_code))
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        return await connector.resolve_subject_sub("test.client22")


async def test_resolve_subject_sub_returns_id_when_user_found() -> None:
    result = await _resolve_subject_sub(
        {
            "beans": [
                {
                    "id": "8a80816f9f3615c8019f3b2735150040",
                    "beanType": "UserAutocompleteResultBean",
                    "principal": "test.client22",
                }
            ]
        }
    )
    assert result == "8a80816f9f3615c8019f3b2735150040"


async def test_resolve_subject_sub_none_when_no_beans() -> None:
    assert await _resolve_subject_sub({"beans": []}) is None


async def test_resolve_subject_sub_none_on_http_error() -> None:
    assert await _resolve_subject_sub({}, status_code=500) is None


async def test_resolve_subject_sub_queries_expected_endpoint_and_params() -> None:
    connector = _make_connector()
    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(
        return_value=_StubResponse({"beans": [{"id": "abc123"}]})
    )
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        result = await connector.resolve_subject_sub("test.client22")

    assert result == "abc123"
    fake_client.authorized_get.assert_awaited_once_with(
        "/webconsole/rest/api/users/search",
        params={"from": 0, "size": 1, "searchTerm": "test.client22"},
    )


async def _get_user_status(body: dict) -> AccountStatus:
    connector = _make_connector()
    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(return_value=_StubResponse(body))
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        result = await connector.get_user_status("some-subject-sub")
    return result


async def test_locked_via_secondary_status_even_when_status_is_active() -> None:
    # The exact original bug: status=ACTIVE alone used to report PASS even
    # though the account was actually locked out from failed login attempts.
    result = await _get_user_status({"status": "ACTIVE", "secondaryStatus": "LOCKED"})
    assert result.status == AccountStatus.LOCKED


async def test_active_when_secondary_status_is_none() -> None:
    result = await _get_user_status({"status": "ACTIVE", "secondaryStatus": None})
    assert result.status == AccountStatus.ACTIVE


async def test_disabled_when_status_is_not_active_and_secondary_status_none() -> None:
    # Any non-"ACTIVE" top-level `status` (not locked) means the account
    # isn't active — reported as DISABLED.
    result = await _get_user_status({"status": "DISABLED", "secondaryStatus": None})
    assert result.status == AccountStatus.DISABLED


async def test_disabled_when_status_is_missing() -> None:
    result = await _get_user_status({"status": None, "secondaryStatus": None})
    assert result.status == AccountStatus.DISABLED


async def test_status_locked_alone_is_not_sufficient_for_locked_verdict() -> None:
    # secondaryStatus is the sole source of truth for the LOCKED verdict — a
    # top-level status=LOCKED with no corroborating secondaryStatus doesn't
    # produce AccountStatus.LOCKED. It still isn't "ACTIVE" though, so it
    # falls through to DISABLED rather than being treated as fine.
    result = await _get_user_status({"status": "LOCKED", "secondaryStatus": None})
    assert result.status == AccountStatus.DISABLED


async def test_password_expired_when_any_principal_list_entry_past_pwd_exp() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [
                {"managedSys": "OPENIAM", "active": True, "status": "ENABLED", "pwdExp": None},
                {
                    "managedSys": "AD Powershell Managed System",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2020-01-01T00:00:00.000Z",
                },
            ],
        }
    )
    assert result.status == AccountStatus.PASSWORD_EXPIRED
    assert "AD Powershell Managed System" in result.detail
    assert "2020-01-01" in result.detail


async def test_password_expired_detail_names_every_expired_login() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [
                {
                    "managedSys": "OPENIAM",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2020-01-01T00:00:00.000Z",
                },
                {
                    "managedSys": "AD Powershell Managed System",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2020-02-01T00:00:00.000Z",
                },
            ],
        }
    )
    assert result.status == AccountStatus.PASSWORD_EXPIRED
    assert "OPENIAM" in result.detail
    assert "2020-01-01" in result.detail
    assert "AD Powershell Managed System" in result.detail
    assert "2020-02-01" in result.detail


async def test_password_reset_url_suppressed_when_only_managed_system_password_expired() -> None:
    # The reset link only resets the OPENIAM login's password — if just a
    # downstream managed system's login expired (not OPENIAM's own), that
    # link wouldn't actually fix the thing that's broken, so it must not
    # be offered.
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [
                {
                    "managedSys": "OPENIAM",
                    "login": "jdoe",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2099-01-01T00:00:00.000Z",
                },
                {
                    "managedSys": "AD Powershell Managed System",
                    "login": "jdoe.ad",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2020-01-01T00:00:00.000Z",
                },
            ],
        }
    )
    assert result.status == AccountStatus.PASSWORD_EXPIRED
    assert result.password_reset_url is None


async def test_password_reset_url_sent_when_openiam_password_expired() -> None:
    # OPENIAM's own login expired — the reset link genuinely fixes this, so
    # it's still offered, same as before this change.
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [
                {
                    "managedSys": "OPENIAM",
                    "login": "jdoe",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2020-01-01T00:00:00.000Z",
                },
            ],
        }
    )
    assert result.status == AccountStatus.PASSWORD_EXPIRED
    assert result.password_reset_url is not None
    assert "login=jdoe" in result.password_reset_url


async def test_active_when_pwd_exp_is_in_the_future() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [
                {
                    "managedSys": "OPENIAM",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2099-01-01T00:00:00.000Z",
                }
            ],
        }
    )
    assert result.status == AccountStatus.ACTIVE


async def test_deprovisioned_when_all_roles_and_groups_end_dated() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [{"managedSys": "OPENIAM", "active": True, "status": "ENABLED"}],
            "roleBeans": [
                {"name": "role1", "accessRightEndDate": "2020-01-01T00:00:00.000Z"},
            ],
            "groupBeans": [
                {"name": "group1", "accessRightEndDate": "2020-01-01T00:00:00.000Z"},
            ],
        }
    )
    assert result.status == AccountStatus.DEPROVISIONED


async def test_not_deprovisioned_when_some_grant_still_active() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [{"managedSys": "OPENIAM", "active": True, "status": "ENABLED"}],
            "roleBeans": [
                {"name": "role1", "accessRightEndDate": "2020-01-01T00:00:00.000Z"},
                {"name": "role2", "accessRightEndDate": None},
            ],
        }
    )
    assert result.status == AccountStatus.ACTIVE


async def test_not_deprovisioned_when_no_grants_at_all() -> None:
    # Never having held any role/group isn't itself evidence of
    # deprovisioning — only *all end-dated* (having held some, now none) is.
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [{"managedSys": "OPENIAM", "active": True, "status": "ENABLED"}],
        }
    )
    assert result.status == AccountStatus.ACTIVE


async def test_deprovisioned_when_principal_list_entry_inactive() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [{"managedSys": "OPENIAM", "active": False, "status": "ENABLED"}],
        }
    )
    assert result.status == AccountStatus.DEPROVISIONED


async def test_deprovisioned_when_principal_list_entry_status_delete() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [{"managedSys": "OPENIAM", "active": True, "status": "DELETE"}],
        }
    )
    assert result.status == AccountStatus.DEPROVISIONED


async def test_locked_wins_over_deprovisioned_signal() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": "LOCKED",
            "principalList": [{"managedSys": "OPENIAM", "active": False, "status": "ENABLED"}],
        }
    )
    assert result.status == AccountStatus.LOCKED


async def test_disabled_wins_over_expired_password() -> None:
    result = await _get_user_status(
        {
            "status": "DISABLED",
            "secondaryStatus": None,
            "principalList": [
                {
                    "managedSys": "OPENIAM",
                    "active": True,
                    "status": "ENABLED",
                    "pwdExp": "2020-01-01T00:00:00.000Z",
                }
            ],
        }
    )
    assert result.status == AccountStatus.DISABLED


async def test_password_reset_url_uses_openiam_managed_sys_login() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [
                {"managedSys": "AD Powershell Managed System", "login": "jdoe.ad"},
                {"managedSys": "OPENIAM", "login": "jdoe"},
            ],
        }
    )
    assert result.password_reset_url is not None
    assert "login=jdoe" in result.password_reset_url
    assert "jdoe.ad" not in result.password_reset_url


async def test_password_reset_url_falls_back_to_first_login_when_no_openiam_entry() -> None:
    result = await _get_user_status(
        {
            "status": "ACTIVE",
            "secondaryStatus": None,
            "principalList": [{"managedSys": "AD Powershell Managed System", "login": "jdoe.ad"}],
        }
    )
    assert result.password_reset_url is not None
    assert "login=jdoe.ad" in result.password_reset_url


async def test_password_reset_url_none_when_no_principal_list() -> None:
    result = await _get_user_status({"status": "ACTIVE", "secondaryStatus": None})
    assert result.password_reset_url is None


async def _get_auth_events(body: dict, status_code: int = 200) -> list:
    connector = _make_connector()
    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(return_value=_StubResponse(body, status_code))
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        return await connector.get_auth_events("some-subject-sub", timedelta(hours=24))


def _audit_bean(
    *,
    action: str = "LOGIN",
    result: str = "SUCCESS",
    error: str = "",
    timestamp: str = "2026-07-16T06:37:16.055+00:00",
) -> dict:
    return {"action": action, "result": result, "error": error, "timestamp": timestamp}


async def test_auth_event_success_has_no_failure_reason() -> None:
    events = await _get_auth_events({"beans": [_audit_bean(result="SUCCESS")]})
    assert len(events) == 1
    assert events[0].success is True
    assert events[0].failure_reason is None


async def test_auth_event_wrong_password_extracts_confirmed_error_code() -> None:
    # errorCode=RESULT_INVALID_PASSWORD, confirmed live against qa422 — the
    # `error` field is a Java exception dump, `action` is just "LOGIN" for
    # every attempt (the bug this test guards against: failure_reason used
    # to be set from `action`, which was never informative).
    events = await _get_auth_events(
        {
            "beans": [
                _audit_bean(
                    result="FAILURE",
                    error=(
                        "Response(status=FAILURE, errorCode=RESULT_INVALID_PASSWORD, "
                        "errorText=null, fieldMappings=null, stacktraceText=...)"
                    ),
                )
            ]
        }
    )
    assert events[0].success is False
    assert events[0].failure_reason == "wrong_password"


async def test_auth_event_invalid_login_extracts_confirmed_error_code() -> None:
    events = await _get_auth_events(
        {
            "beans": [
                _audit_bean(
                    result="FAILURE",
                    error="Response(status=FAILURE, errorCode=INVALID_LOGIN, errorText=null)",
                )
            ]
        }
    )
    assert events[0].failure_reason == "invalid_login"


async def test_auth_event_login_locked_extracts_confirmed_error_code() -> None:
    events = await _get_auth_events(
        {
            "beans": [
                _audit_bean(
                    result="FAILURE",
                    error="Response(status=FAILURE, errorCode=RESULT_LOGIN_LOCKED, errorText=null)",
                )
            ]
        }
    )
    assert events[0].failure_reason == "account_locked"


async def test_auth_event_unmapped_error_code_passed_through_raw() -> None:
    # A real but not-yet-confirmed-and-mapped code shouldn't be discarded —
    # still more useful to the user/support than nothing.
    events = await _get_auth_events(
        {
            "beans": [
                _audit_bean(
                    result="FAILURE",
                    error="Response(status=FAILURE, errorCode=SOME_NEW_CODE, errorText=null)",
                )
            ]
        }
    )
    assert events[0].failure_reason == "SOME_NEW_CODE"


async def test_auth_event_failure_without_error_code_falls_back_to_auth_failed() -> None:
    events = await _get_auth_events({"beans": [_audit_bean(result="FAILURE", error="")]})
    assert events[0].failure_reason == "auth_failed"


async def test_auth_events_empty_on_http_error() -> None:
    assert await _get_auth_events({}, status_code=500) == []


async def _get_effective_permissions(
    body: dict, status_code: int = 200
) -> list[EffectivePermission]:
    connector = _make_connector()
    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(return_value=_StubResponse(body, status_code))
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        return await connector.get_effective_permissions("some-subject-sub", "openiam:default")


async def test_effective_permissions_includes_roles_and_groups() -> None:
    permissions = await _get_effective_permissions(
        {
            "roleBeans": [{"name": "Super Security Admin", "managedSysName": None}],
            "groupBeans": [{"name": "Super Admin Group", "managedSysName": None}],
        }
    )
    assert EffectivePermission(kind="role", name="Super Security Admin", source=None) in permissions
    assert EffectivePermission(kind="group", name="Super Admin Group", source=None) in permissions
    assert len(permissions) == 2


async def test_effective_permissions_empty_when_no_role_or_group_beans() -> None:
    assert await _get_effective_permissions({}) == []


async def test_effective_permissions_empty_on_http_error() -> None:
    assert await _get_effective_permissions({}, status_code=500) == []


async def test_effective_permissions_parses_end_date() -> None:
    permissions = await _get_effective_permissions(
        {
            "roleBeans": [
                {
                    "name": "sod1",
                    "managedSysName": None,
                    "accessRightEndDate": "2026-01-01T00:00:00+00:00",
                }
            ],
        }
    )
    assert permissions[0].end_date == datetime(2026, 1, 1, tzinfo=UTC)


async def test_effective_permissions_end_date_none_when_absent() -> None:
    permissions = await _get_effective_permissions(
        {"roleBeans": [{"name": "sod1", "managedSysName": None}]}
    )
    assert permissions[0].end_date is None


async def _get_permission_audit_events(
    body: dict, status_code: int = 200
) -> list[PermissionAuditEvent]:
    connector = _make_connector()
    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(return_value=_StubResponse(body, status_code))
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        return await connector.get_permission_audit_events(
            "some-subject-sub", timedelta(days=365)
        )


async def test_permission_audit_events_parses_revoke_event() -> None:
    events = await _get_permission_audit_events(
        {
            "beans": [
                {
                    "action": "DELETE_USER_FROM_ROLE",
                    "result": "SUCCESS",
                    "principal": "admin.jane",
                    "timestamp": "2026-07-15T10:00:00+00:00",
                    "targetRoles": [{"key": "role", "value": "Super Security Admin"}],
                    "targetGroups": [],
                }
            ]
        }
    )
    assert len(events) == 1
    event = events[0]
    assert event.action == "DELETE_USER_FROM_ROLE"
    assert event.target_names == ["Super Security Admin"]
    assert event.actor == "admin.jane"
    assert event.occurred_at == datetime(2026, 7, 15, 10, tzinfo=UTC)


async def test_permission_audit_events_parses_group_event() -> None:
    events = await _get_permission_audit_events(
        {
            "beans": [
                {
                    "action": "ADD_USER_TO_GROUP",
                    "result": "SUCCESS",
                    "principal": "admin.jane",
                    "timestamp": "2026-07-15T10:00:00+00:00",
                    "targetRoles": [],
                    "targetGroups": [{"key": "group", "value": "sodgroup1"}],
                }
            ]
        }
    )
    assert events[0].target_names == ["sodgroup1"]


async def test_permission_audit_events_parses_provisioning_event() -> None:
    events = await _get_permission_audit_events(
        {
            "beans": [
                {
                    "action": "PROVISIONING",
                    "result": "FAILED",
                    "principal": "system",
                    "timestamp": "2026-07-15T10:00:00+00:00",
                }
            ]
        }
    )
    assert len(events) == 1
    assert events[0].action == "PROVISIONING"
    assert events[0].result == "FAILED"
    assert events[0].target_names == []


async def test_permission_audit_events_skips_bean_missing_timestamp() -> None:
    events = await _get_permission_audit_events(
        {"beans": [{"action": "DELETE_USER_FROM_ROLE", "targetRoles": []}]}
    )
    assert events == []


async def test_permission_audit_events_empty_on_http_error() -> None:
    assert await _get_permission_audit_events({}, status_code=500) == []


def _dashboard_body(status: str, date_str: str = "07/22/2026 08:00:00") -> dict:
    return {"beans": [{"replies": [{"status": status, "dateStr": date_str}]}]}


async def _check_availability(
    user_body: dict,
    user_status_code: int = 200,
    dashboard_responses: dict[str, dict] | None = None,
    dashboard_status_code: int = 200,
) -> AvailabilityResult:
    connector = _make_connector()
    dashboard_responses = dashboard_responses or {}

    async def fake_authorized_get(path: str, **kwargs: object) -> _StubResponse:
        if path == "/webconsole/rest/api/user/admin/get/some-subject-sub":
            return _StubResponse(user_body, user_status_code)
        if path == "/webconsole/rest/api/managedsys-dashboard/search":
            params = kwargs["params"]
            name = params["name"]  # type: ignore[index]
            body = dashboard_responses.get(name, {"beans": []})
            return _StubResponse(body, dashboard_status_code)
        raise AssertionError(f"unexpected path {path}")

    fake_client = AsyncMock()
    fake_client.authorized_get = AsyncMock(side_effect=fake_authorized_get)
    with patch(
        "app.connectors.openiam.connector.get_openiam_token_client", return_value=fake_client
    ):
        return await connector.check_availability("some-subject-sub")


async def test_check_availability_up_when_all_managed_systems_ok() -> None:
    result = await _check_availability(
        {
            "principalList": [
                {"managedSys": "OPENIAM"},
                {"managedSys": "AD Powershell Managed System"},
            ]
        },
        dashboard_responses={
            "OPENIAM": _dashboard_body("Ok"),
            "AD Powershell Managed System": _dashboard_body("Ok"),
        },
    )
    assert result.status == AvailabilityStatus.UP


async def test_check_availability_down_when_one_managed_system_not_ok() -> None:
    result = await _check_availability(
        {
            "principalList": [
                {"managedSys": "OPENIAM"},
                {"managedSys": "AD Powershell Managed System"},
            ]
        },
        dashboard_responses={
            "OPENIAM": _dashboard_body("Ok"),
            "AD Powershell Managed System": _dashboard_body("Fail"),
        },
    )
    assert result.status == AvailabilityStatus.DOWN
    assert "AD Powershell Managed System" in (result.detail or "")


async def test_check_availability_uses_latest_reply_by_date() -> None:
    # An earlier "Ok" reply is stale — the most recent reply (by dateStr) is
    # what determines the verdict, even though it isn't last in the list.
    result = await _check_availability(
        {"principalList": [{"managedSys": "AD Powershell Managed System"}]},
        dashboard_responses={
            "AD Powershell Managed System": {
                "beans": [
                    {
                        "replies": [
                            {"status": "Fail", "dateStr": "07/22/2026 09:00:00"},
                            {"status": "Ok", "dateStr": "07/20/2026 08:00:00"},
                        ]
                    }
                ]
            }
        },
    )
    assert result.status == AvailabilityStatus.DOWN


async def test_check_availability_up_when_no_managed_systems() -> None:
    result = await _check_availability({"principalList": []})
    assert result.status == AvailabilityStatus.UP


async def test_check_availability_indeterminate_system_does_not_cause_down() -> None:
    # No dashboard beans at all for this managed system (e.g. OPENIAM's core
    # identity record, managedSysId "0", isn't itself a dashboard entry) —
    # that's indeterminate, not a confirmed failure.
    result = await _check_availability(
        {"principalList": [{"managedSys": "OPENIAM"}]},
        dashboard_responses={"OPENIAM": {"beans": []}},
    )
    assert result.status == AvailabilityStatus.UP


async def test_check_availability_degraded_on_user_lookup_error() -> None:
    result = await _check_availability({}, user_status_code=500)
    assert result.status == AvailabilityStatus.DEGRADED
