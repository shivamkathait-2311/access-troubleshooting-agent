from fastapi import APIRouter

from app.core.config import settings
from app.core.killswitch import is_agent_killed

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "version": settings.VERSION,
        "environment": settings.ENV,
        "agent_kill_switch_engaged": is_agent_killed(),
    }
