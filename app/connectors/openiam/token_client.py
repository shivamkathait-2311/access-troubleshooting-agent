import asyncio
import json
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from app.connectors.openiam.ssl_context import build_ssl_context
from app.core.config import Settings, settings
from app.core.exceptions import OpenIAMAuthError
from app.db.redis import redis_manager

_LOGIN_PATH = "/idp/rest/api/auth/public/login"
_AUTHORIZE_PATH = "/idp/oauth2/authorize"
_TOKEN_INFO_PATH = "/idp/oauth2/token/info"
_REDIS_KEY = "openiam:access_token"
_REDIS_COOKIES_KEY = "openiam:session_cookies"

# Fallback token lifetime used only if neither the authorize redirect's
# fragment nor the token/info response exposes an expiry — confirmed against
# a real OpenIAM staging instance's login/authorize flow, but the introspection
# response shape wasn't available to verify at the time this was written.
# Deliberately short, to force a re-login rather than risk over-caching a
# token past its real expiry.
_FALLBACK_TOKEN_TTL_SECONDS = 300


class OpenIAMTokenClient:
    """Admin-credential token client for OpenIAM.

    Real flow (confirmed against a staging Postman collection — NOT a
    standard OAuth2 grant type):
      1. POST /idp/rest/api/auth/public/login {login, password} -> an
         `authToken` (OpenIAM's native session token, in `tokenInfo.authToken`).
      2. GET /idp/oauth2/authorize?client_id=...&response_type=...&redirect_uri=...
         with `Authorization: Bearer <authToken>` -> a 302 whose `Location`
         header carries `access_token` (and possibly `expires_in`) in the
         URL fragment (implicit-grant style).
      3. The access_token is what every other OpenIAM REST call uses as its
         own Bearer token.

    Caches the access token and refreshes it proactively before expiry.
    Two-tier cache: an in-process field (fastest, avoids a Redis round-trip
    on every call) backed by Redis (shared across processes and survives
    restarts — a fresh process checks Redis before doing a real login).

    Also caches session cookies alongside the token: confirmed live that
    some endpoints (e.g. auditlog/search) reject the OAuth bearer token
    alone (redirect to /idp/login) and need the session cookies the login
    call itself sets (OPENIAM_SESSION_ID_COOKIE, SESSION, etc.) — cookies
    otherwise only exist in whichever process happened to do the actual
    login, so they're cached the same way as the token to survive a
    Redis-cache-hit that skips a fresh login entirely.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str,
        username: str,
        password: str,
        redirect_uri: str,
        oauth_response_type: str,
        refresh_margin_seconds: int,
    ):
        self._client_id = client_id
        self._username = username
        self._password = password
        self._redirect_uri = redirect_uri
        self._oauth_response_type = oauth_response_type
        self._refresh_margin_seconds = refresh_margin_seconds

        self._http = httpx.AsyncClient(base_url=base_url, timeout=30.0, verify=build_ssl_context())
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def get_access_token(self) -> str:
        if self._access_token is not None and time.monotonic() < self._expires_at:
            return self._access_token

        async with self._lock:
            # Re-check after acquiring the lock: another caller may have
            # already refreshed while we were waiting.
            if self._access_token is not None and time.monotonic() < self._expires_at:
                return self._access_token

            cached = await self._read_cached_token()
            if cached is not None:
                token, remaining_ttl = cached
                self._access_token = token
                self._expires_at = time.monotonic() + remaining_ttl
                return self._access_token

            await self._login_and_authorize()
            assert self._access_token is not None
            return self._access_token

    async def _read_cached_token(self) -> tuple[str, int] | None:
        """A still-valid token another process (or an earlier run of this
        one) already cached in Redis, as (token, remaining_ttl_seconds) —
        or None if nothing usable is cached there. Also restores that
        login's session cookies onto this client, since this process may
        never have logged in itself."""
        await redis_manager.ensure_connected()
        token = await redis_manager.client.get(_REDIS_KEY)
        if token is None:
            return None
        ttl = await redis_manager.client.ttl(_REDIS_KEY)
        if ttl is None or ttl <= 0:
            return None
        await self._restore_cached_cookies()
        return token, ttl

    async def _restore_cached_cookies(self) -> None:
        cookies_json = await redis_manager.client.get(_REDIS_COOKIES_KEY)
        if not cookies_json:
            return
        for name, value in json.loads(cookies_json).items():
            self._http.cookies.set(name, value)

    async def _login_and_authorize(self) -> None:
        # Start from a clean jar so what we cache afterward is exactly this
        # login's cookies, not a stale mix from a previous session.
        self._http.cookies.clear()

        auth_token = await self._fetch_auth_token()
        access_token, expires_in = await self._authorize(auth_token)

        if expires_in is None:
            expires_in = await self._introspect_expiry(access_token)

        ttl = expires_in if expires_in is not None else _FALLBACK_TOKEN_TTL_SECONDS
        effective_ttl = max(ttl - self._refresh_margin_seconds, 1)

        self._access_token = access_token
        self._expires_at = time.monotonic() + effective_ttl

        cookies = {c.name: c.value for c in self._http.cookies.jar}

        await redis_manager.ensure_connected()
        await redis_manager.client.set(_REDIS_KEY, access_token, ex=effective_ttl)
        await redis_manager.client.set(_REDIS_COOKIES_KEY, json.dumps(cookies), ex=effective_ttl)

    async def _fetch_auth_token(self) -> str:
        response = await self._http.post(
            _LOGIN_PATH,
            json={"login": self._username, "password": self._password},
        )
        if response.status_code >= 400:
            raise OpenIAMAuthError(
                f"OpenIAM login failed: {response.status_code} {response.text}"
            )
        body = response.json()
        auth_token = body.get("tokenInfo", {}).get("authToken")
        if not auth_token or body.get("status") != 200:
            raise OpenIAMAuthError(f"OpenIAM login returned no authToken: {body}")
        return str(auth_token)

    async def _authorize(self, auth_token: str) -> tuple[str, int | None]:
        response = await self._http.get(
            _AUTHORIZE_PATH,
            params={
                "client_id": self._client_id,
                "response_type": self._oauth_response_type,
                "redirect_uri": self._redirect_uri,
            },
            headers={"Authorization": f"Bearer {auth_token}"},
            follow_redirects=False,
        )
        if response.status_code != 302:
            raise OpenIAMAuthError(
                f"OpenIAM authorize did not redirect: {response.status_code} {response.text}"
            )
        location = response.headers.get("location")
        if not location or "#" not in location:
            raise OpenIAMAuthError(f"OpenIAM authorize redirect had no fragment: {location!r}")

        fragment = urlsplit(location).fragment
        params = dict(parse_qsl(fragment))
        access_token = params.get("access_token")
        if not access_token:
            raise OpenIAMAuthError(f"OpenIAM authorize fragment had no access_token: {fragment!r}")

        expires_in = int(params["expires_in"]) if "expires_in" in params else None
        return access_token, expires_in

    async def _introspect_expiry(self, access_token: str) -> int | None:
        response = await self._http.get(_TOKEN_INFO_PATH, params={"token": access_token})
        if response.status_code >= 400:
            return None
        body = response.json()
        for key in ("expires_in", "expiresIn", "exp"):
            if key in body:
                return int(body[key])
        return None

    async def authorized_get(self, path: str, **kwargs: Any) -> httpx.Response:
        """GET against self._http (already has the right base_url + TLS
        fix) with a fresh Bearer token attached. Returns the raw Response —
        callers inspect status/redirects themselves, since OpenIAM's
        failure modes here are a redirect to /idp/login, not a clean
        401/403."""
        token = await self.get_access_token()
        return await self._http.get(path, headers={"Authorization": f"Bearer {token}"}, **kwargs)

    async def close(self) -> None:
        await self._http.aclose()


_client: OpenIAMTokenClient | None = None


def get_openiam_token_client(config: Settings = settings) -> OpenIAMTokenClient:
    """Lazy module-level singleton. ConnectorRegistry only passes
    `(connector_id, config)` into connector constructors, so a connector
    needing this shared token client reaches for it here rather than via
    FastAPI `Depends`."""
    global _client
    if _client is None:
        _client = OpenIAMTokenClient(
            base_url=config.OPENIAM_BASE_URL,
            client_id=config.OPENIAM_CLIENT_ID,
            username=config.OPENIAM_ADMIN_USERNAME,
            password=config.OPENIAM_ADMIN_PASSWORD,
            redirect_uri=config.OPENIAM_REDIRECT_URI,
            oauth_response_type=config.OPENIAM_OAUTH_RESPONSE_TYPE,
            refresh_margin_seconds=config.OPENIAM_TOKEN_REFRESH_MARGIN_SECONDS,
        )
    return _client
