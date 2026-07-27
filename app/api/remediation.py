import uuid

from fastapi import APIRouter, Depends

from app.core.security import Principal
from app.dependencies.auth import get_principal
from app.dependencies.services import get_remediation_service
from app.remediation.killswitch import assert_remediation_not_killed
from app.schemas.remediation import RemediationActionResponse, RemediationRequest
from app.services.remediation_service import RemediationService

router = APIRouter(prefix="/remediation", tags=["remediation"])


@router.post("/request", response_model=RemediationActionResponse)
async def request_remediation(
    body: RemediationRequest,
    principal: Principal = Depends(get_principal),
    remediation_service: RemediationService = Depends(get_remediation_service),
) -> RemediationActionResponse:
    """Creates a pending remediation action. Actual execution — including
    tier/approval/kill-switch gating — happens on POST /{action_id}/execute,
    handled entirely by RemediationExecutor (see app/remediation/executor.py).
    """
    raise NotImplementedError


@router.post("/{action_id}/execute")
async def execute_remediation(
    action_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    remediation_service: RemediationService = Depends(get_remediation_service),
) -> dict[str, object]:
    assert_remediation_not_killed()
    raise NotImplementedError
