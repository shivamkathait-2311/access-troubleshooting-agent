"""Scheduled self-diagnosis: periodically runs the orchestrator against the
agent's own service-account access on each connector, so credential
expiry/misconfiguration is caught before a real user hits it.

Run with: uv run arq app.workers.self_diagnosis_worker.WorkerSettings
"""

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import logger_adapter


async def run_self_diagnosis(ctx: dict[str, Any]) -> None:
    """Cron job body. Phase 0: not yet implemented — will iterate the
    PolicyStore's systems and call orchestrator.run() with the agent's own
    identity as both requester and subject."""
    logger_adapter.info("Self-diagnosis cron fired (not yet implemented)")
    raise NotImplementedError


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    cron_jobs = [cron(run_self_diagnosis, hour=set(range(24)), minute=0)]
