from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async test client bound directly to the ASGI app (no network socket).

    Note: ASGITransport does NOT run the app's lifespan (no policy-store
    load, no Redis connect) — fine for routes that don't touch app.state.
    Tests exercising intake/diagnostics/remediation must override the
    relevant `app.dependencies.services.get_*` dependencies rather than
    rely on a real Postgres/Redis/policy-store being loaded.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
