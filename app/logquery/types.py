from datetime import datetime

from pydantic import BaseModel


class NormalizedIdentity(BaseModel):
    """A subject identity normalized to a common shape across log sources
    that may key on username, UUID, or email inconsistently."""

    username: str | None = None
    uuid: str | None = None
    email: str | None = None
    source_system: str


class LogEvent(BaseModel):
    timestamp: datetime
    source: str
    raw: str
    identity: NormalizedIdentity
    correlation_id: str | None = None
