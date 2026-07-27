from abc import ABC, abstractmethod
from datetime import timedelta

from app.logquery.types import LogEvent, NormalizedIdentity


class LogQueryAdapter(ABC):
    """Per-source log adapter interface. Adding a new backend (Loki,
    CloudWatch, raw files — deferred past Phase 0) means implementing this
    interface, not changing any caller."""

    @abstractmethod
    async def search(
        self,
        identity: NormalizedIdentity,
        time_range: timedelta,
        correlation_id: str | None = None,
    ) -> list[LogEvent]:
        raise NotImplementedError
