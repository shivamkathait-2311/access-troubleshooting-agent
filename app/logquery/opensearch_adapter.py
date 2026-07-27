from datetime import timedelta

from app.logquery.base import LogQueryAdapter
from app.logquery.types import LogEvent, NormalizedIdentity


class OpenSearchLogAdapter(LogQueryAdapter):
    """Phase 0 stub for OpenSearch/ELK. The only log backend wired up for
    now — Loki/CloudWatch/raw-file adapters are deliberately deferred; add
    them as siblings implementing the same LogQueryAdapter interface."""

    async def search(
        self,
        identity: NormalizedIdentity,
        time_range: timedelta,
        correlation_id: str | None = None,
    ) -> list[LogEvent]:
        raise NotImplementedError
