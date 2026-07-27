from fastapi import APIRouter, Request

router = APIRouter(prefix="/intake/teams", tags=["intake-surfaces"])


@router.post("/events")
async def teams_events(request: Request) -> dict[str, object]:
    """MS Teams Bot Framework webhook receiver. Phase 0 stub — Phase 1 adds
    Bot Framework JWT validation before touching the payload, then maps the
    activity to ComplaintIntake and calls IntakeService.submit()."""
    raise NotImplementedError
