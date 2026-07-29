import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from app.connectors.base import ConnectorSPI
from app.connectors.openiam.ssl_context import build_ssl_context
from app.connectors.openiam.token_client import OpenIAMTokenClient, get_openiam_token_client
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
from app.core.config import settings

# secondaryStatus is OpenIAM's actual failed-login-lockout signal (confirmed
# live against qa422: GET /webconsole/rest/api/user/admin/get/{id} ->
# {"status": "ACTIVE", "secondaryStatus": "LOCKED", ...} — an account can be
# status=ACTIVE while secondaryStatus reports it locked). get_user_status()
# checks this first: locked -> AccountStatus.LOCKED. Then _is_deprovisioned()
# (see below). Then the top-level `status` field is read as a binary
# active/not-active signal (confirmed live) rather than its full assumed
# ~20-value lifecycle enum: "ACTIVE" -> AccountStatus.ACTIVE, anything else
# (any other value, or missing/null) -> AccountStatus.DISABLED. Finally
# _expired_password_logins() (principalList[].pwdExp).
_LOCKED_SECONDARY_STATUSES = {"LOCKED", "LOCKED_ADMIN"}

# Best-guess, NOT confirmed live — only "ENABLED" has been seen in a real
# principalList entry so far. Flagged the same way DISABLED's raw status
# value was before that got confirmed; revisit once a real deprovisioned
# login is seen.
_DELETED_LOGIN_STATUSES = {"DELETE"}


def _is_deprovisioned(
    principal_list: list[dict[str, Any]],
    role_beans: list[dict[str, Any]],
    group_beans: list[dict[str, Any]],
) -> bool:
    """Two independent signals, either is sufficient: (1) a managed-system
    login was deleted/deactivated (principalList[].status or .active), or
    (2) the user held roles/groups but every single one is now end-dated —
    i.e. zero currently-active grants. Roles/groups aren't scoped to a
    specific managed system in OpenIAM's model, so (2) looks at all of
    them, not just ones tied to the system being diagnosed. Never having
    held any role/group at all is NOT by itself evidence of deprovisioning
    (that's closer to NOT_FOUND/never-provisioned) — only *all end-dated*
    counts."""
    if any(
        entry.get("status") in _DELETED_LOGIN_STATUSES or entry.get("active") is False
        for entry in principal_list
    ):
        return True

    grants = role_beans + group_beans
    if not grants:
        return False

    now = datetime.now(UTC)
    return all(
        (end := _parse_end_date(bean.get("accessRightEndDate"))) is not None and end < now
        for bean in grants
    )


def _expired_password_logins(
    principal_list: list[dict[str, Any]],
) -> list[tuple[str, datetime]]:
    """Every managed-system login (principalList entry) whose pwdExp has
    passed, paired with its managedSys name and expiry date — checked
    across all of them, not just one preferred login. Used both to decide
    PASSWORD_EXPIRED and to tell the user specifically which login(s)
    expired and when."""
    now = datetime.now(UTC)
    expired: list[tuple[str, datetime]] = []
    for entry in principal_list:
        exp = _parse_end_date(entry.get("pwdExp"))
        if exp is not None and exp < now:
            expired.append((entry.get("managedSys") or "unknown system", exp))
    return expired


def _format_expired_password_detail(expired: list[tuple[str, datetime]]) -> str:
    return ", ".join(f"{name} (expired {exp.date().isoformat()})" for name, exp in expired)

# Grant-change actions: confirmed valid against OpenIAM's all-audit-actions
# enum. Used to answer "when was this specific role/group revoked."
_GRANT_CHANGE_ACTIONS = [
    "ADD_USER_TO_ROLE",
    "DELETE_USER_FROM_ROLE",
    "ADD_USER_TO_GROUP",
    "DELETE_USER_FROM_GROUP",
]

# Provisioning/reconciliation actions: also confirmed as valid action names,
# but their `result`/`responseCode` semantics (success vs. failure) are NOT
# confirmed — nothing in this codebase interprets these as pass/fail yet.
# See get_permission_audit_events(): these are surfaced as advisory-only
# raw events for step4_authorization.py to mention, never to gate a verdict.
_SYNC_ACTIONS = [
    "PROVISIONING",
    "GROUP_PROVISIONING",
    "SEND_REPORT_OF_FAILED_PROVISION_REQUESTS",
    "RETRY_PROVISIONING",
    "RECONCILE_USER",
    "RECONCILE_IDM_WITH_TARGET",
    "RECONCILE_TARGET_WITH_IDM",
    "RECONCILIATION_RECORD_FALSE",
    "SYNCHRONIZATION_ORPHAN",
]


def _select_login(principal_list: list[dict[str, Any]]) -> str | None:
    """EditUserModel.principalList holds one LoginBean per managed system.
    Prefer the OPENIAM-native login (the one actually used to sign into the
    system being diagnosed here) over a synced login on some other managed
    system; fall back to the first entry if OPENIAM isn't present."""
    for entry in principal_list:
        if entry.get("managedSys") == "OPENIAM":
            return entry.get("login")
    return principal_list[0].get("login") if principal_list else None


def _build_password_reset_url(base_url: str, login: str) -> str:
    """{login} is the account's UserBean.principal, not its internal userId
    — the two are different identifiers on OpenIAM. The template itself
    (OpenIAM's self-service "forgot password" flow) is configurable via
    settings.OPENIAM_PASSWORD_RESET_URL_TEMPLATE, not hardcoded here."""
    encoded_login = quote(login, safe="")
    return settings.OPENIAM_PASSWORD_RESET_URL_TEMPLATE.format(
        base_url=base_url.rstrip("/"), login=encoded_login
    )


# The real per-attempt failure reason lives in `error` (a Java exception
# dump, e.g. "Response(status=FAILURE, errorCode=RESULT_INVALID_PASSWORD,
# errorText=null, ..., stacktraceText=...")), NOT in `action` (which is
# just "LOGIN" for every attempt, success or fail — a prior version of this
# code used `action` as failure_reason, which was never actually
# informative). `errorCode=` is a consistently-formatted substring within
# that dump — confirmed live against qa422 across a wide sample of real
# failed logins. Three values confirmed so far; anything else observed
# gets passed through raw rather than dropped, since an unmapped-but-real
# code is still more useful than nothing — see step3_auth_events.py, which
# uses this directly as cause_code.
_AUTH_FAILURE_CAUSES = {
    "RESULT_INVALID_PASSWORD": "wrong_password",
    "INVALID_LOGIN": "invalid_login",
    "RESULT_LOGIN_LOCKED": "account_locked",
}
_ERROR_CODE_PATTERN = re.compile(r"errorCode=([A-Za-z0-9_]+)")


def _extract_failure_cause(bean: dict[str, Any]) -> str | None:
    match = _ERROR_CODE_PATTERN.search(str(bean.get("error") or ""))
    if match is None:
        return None
    raw_code = match.group(1)
    return _AUTH_FAILURE_CAUSES.get(raw_code, raw_code)


def _parse_audit_bean(bean: dict[str, Any]) -> AuthEvent | None:
    """Maps one `IdmAuditLogDoc` record to our AuthEvent shape — field
    names (`timestamp`, `result`, `clientIP`) confirmed against OpenIAM's
    published OpenAPI spec (components.schemas.IdmAuditLogDoc).
    `failure_reason` comes from `_extract_failure_cause` (the `error`
    field's embedded errorCode) — see the comment on `_AUTH_FAILURE_CAUSES`
    above. `result`'s exact success/failure string values aren't given as
    an enum in the spec (typed as a plain string), so this matches a
    reasonably permissive set of "success" spellings rather than a single
    hardcoded literal. Returns None for a record missing a parseable
    timestamp, rather than raising — one bad/unexpected record shouldn't
    blow up the whole funnel step.
    """
    raw_timestamp = bean.get("timestamp")
    if raw_timestamp is None:
        return None
    try:
        timestamp = datetime.fromisoformat(str(raw_timestamp))
    except ValueError:
        return None

    result = str(bean.get("result", "")).upper()
    success = result in {"SUCCESS", "PASS", "PASSED", "OK"}

    return AuthEvent(
        timestamp=timestamp,
        success=success,
        failure_reason=None if success else (_extract_failure_cause(bean) or "auth_failed"),
        source_ip=bean.get("clientIP"),
    )


def _latest_reply(replies: list[dict[str, Any]]) -> dict[str, Any] | None:
    """`ManagedSysStatusBean.replies` is the connection-test history for one
    managed system; we only care about the most recent attempt. `dateStr` is
    formatted MM/DD/YYYY HH:MM:SS (confirmed against a live sample) — falls
    back to the last list entry if a `dateStr` is missing/unparseable rather
    than raising, same defensiveness as _parse_audit_bean."""
    if not replies:
        return None

    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for reply in replies:
        try:
            parsed.append(
                (datetime.strptime(str(reply.get("dateStr")), "%m/%d/%Y %H:%M:%S"), reply)
            )
        except ValueError:
            continue

    if not parsed:
        return replies[-1]
    return max(parsed, key=lambda entry: entry[0])[1]


def _parse_end_date(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _parse_permission_audit_event(bean: dict[str, Any]) -> PermissionAuditEvent | None:
    """Maps one `IdmAuditLogDoc` record to our PermissionAuditEvent shape.
    `targetRoles`/`targetGroups` (each `AuditLogAttributeTupleDoc`, a
    {key, value} pair) name the affected role/group in `value` — confirmed
    against the OpenAPI spec, though untested against a real populated
    grant-change/provisioning event in this environment. Same
    missing-timestamp defensiveness as _parse_audit_bean."""
    raw_timestamp = bean.get("timestamp")
    if raw_timestamp is None:
        return None
    try:
        occurred_at = datetime.fromisoformat(str(raw_timestamp))
    except ValueError:
        return None

    target_names = [
        str(entry["value"])
        for entry in (bean.get("targetRoles") or []) + (bean.get("targetGroups") or [])
        if entry.get("value")
    ]

    return PermissionAuditEvent(
        action=str(bean.get("action", "")),
        result=bean.get("result"),
        target_names=target_names,
        actor=bean.get("principal"),
        occurred_at=occurred_at,
    )


class OpenIAMConnector(ConnectorSPI):
    """Talks to an OpenIAM instance. `base_url` comes from the policy's
    `connector.base_url` (self.config), falling back to the global
    settings.OPENIAM_BASE_URL if a policy doesn't set one — so a future
    policy can point at a different OpenIAM instance without a code change.

    Known limitation: the admin credentials used to authenticate
    (OPENIAM_ADMIN_USERNAME/PASSWORD/CLIENT_ID/REDIRECT_URI) are still
    global settings, consumed by the single lazy singleton
    get_openiam_token_client() — if two policies ever needed genuinely
    different OpenIAM instances with different credentials, this would
    still authenticate wrong for one of them. Not fixed here; would need
    per-connector-instance token clients sourced via credential_path/Vault.

    """

    async def resolve_subject_sub(self, login_id: str) -> str | None:
        """Turns a login/principal string (what the user actually types to
        sign in, e.g. "test.client22") into OpenIAM's internal userId (the
        `subject_sub` every other method on this connector expects). Returns
        None if the search finds no match — intake treats that as "no user
        found for this login", not an error to bubble up as a 500."""
        client = get_openiam_token_client()
        response = await client.authorized_get(
            "/webconsole/rest/api/users/search",
            params={"from": 0, "size": 1, "searchTerm": login_id},
        )
        if response.status_code >= 400:
            return None

        beans = response.json().get("beans") or []
        if not beans:
            return None

        resolved_id = beans[0].get("id")
        return str(resolved_id) if resolved_id is not None else None

    async def check_availability(self, subject_sub: str) -> AvailabilityResult:
        """Not a generic ping — checks whether *this user's* managed
        system(s) are actually working, via OpenIAM's own per-managed-system
        connection-test status. Reuses the same user/admin/get response as
        get_user_status() to find which managed systems (principalList[].managedSys)
        this user has, then looks each one up in the managed-sys dashboard
        search API for its latest connection-test reply. "Ok" is the only
        confirmed-good status value seen in a live sample — any other value
        (or no reply at all after the lookup succeeds) is treated as down."""
        client = get_openiam_token_client()
        user_response = await client.authorized_get(
            f"/webconsole/rest/api/user/admin/get/{subject_sub}"
        )
        if user_response.status_code >= 400:
            return AvailabilityResult(
                status=AvailabilityStatus.DEGRADED,
                detail=(
                    f"Could not look up managed systems: user/admin/get returned "
                    f"{user_response.status_code}"
                ),
                checked_at=datetime.now(UTC),
            )

        principal_list = user_response.json().get("principalList") or []
        managed_sys_names = {
            entry["managedSys"] for entry in principal_list if entry.get("managedSys")
        }
        if not managed_sys_names:
            return AvailabilityResult(
                status=AvailabilityStatus.UP,
                detail="No managed systems found for this user.",
                checked_at=datetime.now(UTC),
            )

        results = await asyncio.gather(
            *(self._check_managed_system(client, name) for name in managed_sys_names)
        )
        down = [(name, reply_status) for name, reply_status in results if reply_status is False]

        if down:
            detail = "Managed system(s) not working: " + ", ".join(
                f"{name} (status not Ok)" for name, _ in down
            )
            return AvailabilityResult(
                status=AvailabilityStatus.DOWN, detail=detail, checked_at=datetime.now(UTC)
            )

        return AvailabilityResult(
            status=AvailabilityStatus.UP,
            detail=f"All managed systems OK: {', '.join(sorted(managed_sys_names))}",
            checked_at=datetime.now(UTC),
        )

    async def _check_managed_system(
        self, client: OpenIAMTokenClient, managed_sys_name: str
    ) -> tuple[str, bool | None]:
        """Returns (name, is_ok) where is_ok is None if we couldn't determine
        a status at all (no matching bean/reply, or the lookup itself
        failed) — indeterminate systems don't drag the overall verdict to
        DOWN on their own, only a confirmed non-"Ok" reply does."""
        response = await client.authorized_get(
            "/webconsole/rest/api/managedsys-dashboard/search",
            params={"name": managed_sys_name, "from": 0, "size": 10},
        )
        if response.status_code >= 400:
            return managed_sys_name, None

        beans = response.json().get("beans") or []
        if not beans:
            return managed_sys_name, None

        latest_reply = _latest_reply(beans[0].get("replies") or [])
        if latest_reply is None:
            return managed_sys_name, None

        return managed_sys_name, latest_reply.get("status") == "Ok"

    async def get_user_status(self, subject_sub: str) -> UserStatusResult:
        client = get_openiam_token_client()
        response = await client.authorized_get(
            f"/webconsole/rest/api/user/admin/get/{subject_sub}"
        )
        if response.status_code >= 400:
            return UserStatusResult(
                status=AccountStatus.NOT_FOUND,
                detail=f"OpenIAM user/admin/get returned {response.status_code}",
            )

        body = response.json()
        raw_status = body.get("status")
        raw_secondary_status = body.get("secondaryStatus")
        principal_list = body.get("principalList") or []

        role_beans = body.get("roleBeans") or []
        group_beans = body.get("groupBeans") or []
        expired_password_logins = _expired_password_logins(principal_list)

        if raw_secondary_status in _LOCKED_SECONDARY_STATUSES:
            status = AccountStatus.LOCKED
        elif _is_deprovisioned(principal_list, role_beans, group_beans):
            status = AccountStatus.DEPROVISIONED
        elif raw_status != "ACTIVE":
            status = AccountStatus.DISABLED
        elif expired_password_logins:
            status = AccountStatus.PASSWORD_EXPIRED
        else:
            status = AccountStatus.ACTIVE

        login = _select_login(principal_list)
        password_reset_url = None
        if login:
            base_url = self.config.get("base_url") or settings.OPENIAM_BASE_URL
            password_reset_url = _build_password_reset_url(base_url, login)

        if status == AccountStatus.PASSWORD_EXPIRED:
            detail = _format_expired_password_detail(expired_password_logins)
            if not any(name == "OPENIAM" for name, _ in expired_password_logins):
                # Only a downstream managed system's login expired, not the
                # OPENIAM login itself — the reset link only resets the
                # OPENIAM password, so it wouldn't actually fix this; don't
                # offer it.
                password_reset_url = None
        else:
            detail = f"OpenIAM status={raw_status} secondaryStatus={raw_secondary_status}"

        return UserStatusResult(
            status=status,
            detail=detail,
            password_reset_url=password_reset_url,
        )

    async def get_auth_events(self, subject_sub: str, time_window: timedelta) -> list[AuthEvent]:
        client = get_openiam_token_client()
        now = datetime.now(UTC)
        response = await client.authorized_get(
            "/webconsole/rest/api/auditlog/search",
            params={
                "userId": subject_sub,
                "fromDate": int((now - time_window).timestamp() * 1000),
                "toDate": int(now.timestamp() * 1000),
                "actions[]": ["LOGIN", "DO_LOGIN"],
                "from": 0,
                "size": 10,
                # Required by the endpoint (timezone offset in minutes) —
                # confirmed via the OpenAPI spec; we run entirely in UTC.
                "offset": 0,
            },
        )
        if response.status_code >= 400:
            return []

        beans = response.json().get("beans", [])
        events = (_parse_audit_bean(bean) for bean in beans)
        return [event for event in events if event is not None]

    async def get_effective_permissions(
        self, subject_sub: str, resource: str
    ) -> list[EffectivePermission]:
        """Sourced from the same admin/get response as get_user_status() —
        its roleBeans/groupBeans cover both grant types the design doc calls
        for ("missing role/group"), rather than the roles-only dedicated
        endpoint this used to call."""
        client = get_openiam_token_client()
        response = await client.authorized_get(
            f"/webconsole/rest/api/user/admin/get/{subject_sub}"
        )
        if response.status_code >= 400:
            return []

        body = response.json()
        permissions = [
            EffectivePermission(
                kind="role",
                name=bean["name"],
                source=bean.get("managedSysName"),
                end_date=_parse_end_date(bean.get("accessRightEndDate")),
            )
            for bean in body.get("roleBeans") or []
        ]
        permissions += [
            EffectivePermission(
                kind="group",
                name=bean["name"],
                source=bean.get("managedSysName"),
                end_date=_parse_end_date(bean.get("accessRightEndDate")),
            )
            for bean in body.get("groupBeans") or []
        ]
        return permissions

    async def get_required_permissions(self, resource: str) -> list[RequiredPermission]:
        """Not a live API call — reads the policy-declared role map merged
        into this connector's config by DiagnosticService (see
        SystemPolicy.role_permission_map)."""
        mapping: list[dict[str, Any]] = self.config.get("role_permission_map", [])
        for entry in mapping:
            if entry["resource"] == resource:
                return [
                    RequiredPermission(kind="role", name=str(role))
                    for role in entry["required_roles"]
                ]
        return []

    async def get_permission_audit_events(
        self, subject_sub: str, time_window: timedelta
    ) -> list[PermissionAuditEvent]:
        """Grant/revoke events (who removed what, when) plus
        provisioning/reconciliation events (advisory-only stale-sync
        signal — see _SYNC_ACTIONS) from the same audit log already used
        by get_auth_events()."""
        client = get_openiam_token_client()
        now = datetime.now(UTC)
        response = await client.authorized_get(
            "/webconsole/rest/api/auditlog/search",
            params={
                "userId": subject_sub,
                "fromDate": int((now - time_window).timestamp() * 1000),
                "toDate": int(now.timestamp() * 1000),
                "actions[]": _GRANT_CHANGE_ACTIONS + _SYNC_ACTIONS,
                "from": 0,
                "size": 50,
                "offset": 0,
            },
        )
        if response.status_code >= 400:
            return []

        beans = response.json().get("beans", [])
        events = (_parse_permission_audit_event(bean) for bean in beans)
        return [event for event in events if event is not None]

    async def _authorized_client(self) -> httpx.AsyncClient:
        token = await get_openiam_token_client().get_access_token()
        base_url = self.config.get("base_url") or settings.OPENIAM_BASE_URL
        return httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
            verify=build_ssl_context(),
        )
