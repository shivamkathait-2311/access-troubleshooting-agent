from fastapi import APIRouter, Request

router = APIRouter(prefix="/intake/slack", tags=["intake-surfaces"])


@router.post("/events")
async def slack_events(request: Request) -> dict[str, object]:
    """Slack Events API webhook receiver. Phase 0 stub — Phase 1 adds
    request signature verification against settings.SLACK_SIGNING_SECRET
    (per Slack's HMAC scheme) before touching the payload, then maps the
    event to ComplaintIntake and calls IntakeService.submit()."""
    raise NotImplementedError
