from redis.asyncio import Redis

from app.core.config import settings


class RedisManager:
    """Connection lifecycle manager, wired into app.main's lifespan."""

    def __init__(self, url: str):
        self.url = url
        self._client: Redis | None = None

    async def connect(self) -> None:
        self._client = Redis.from_url(self.url, decode_responses=True)
        await self._client.ping()

    async def ensure_connected(self) -> None:
        """Idempotent connect, for code paths that may run outside the
        FastAPI app's lifespan (e.g. the arq worker process, or a direct
        CLI invocation of a job function)."""
        if self._client is None:
            await self.connect()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("RedisManager.connect() has not been called yet")
        return self._client


redis_manager = RedisManager(settings.REDIS_URL)
