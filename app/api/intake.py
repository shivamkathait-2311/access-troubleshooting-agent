import uuid

from fastapi import APIRouter, Depends

from app.core.killswitch import assert_agent_not_killed
from app.core.security import Principal
from app.dependencies.services import get_diagnostic_service, get_intake_service, get_policy_store
from app.orchestrator.verdict_messages import build_verdict_message
from app.policy.store import PolicyStore
from app.schemas.intake import (
    ComplaintIntake,
    EscalationRequest,
    EscalationResponse,
    IntakeDiagnosisResponse,
    SystemSummary,
)
from app.services.diagnostic_service import DiagnosticService
from app.services.intake_service import IntakeService

router = APIRouter(prefix="/intake", tags=["intake"])


@router.get("/systems", response_model=list[SystemSummary])
async def list_systems(
    policy_store: PolicyStore = Depends(get_policy_store),
) -> list[SystemSummary]:
    """Lets a caller (FE dropdown, Slack bot, etc.) discover valid
    ComplaintIntake.system_id values at request time, instead of hardcoding
    an enum — reflects whatever policy YAML files are currently loaded, so
    onboarding a new system (new YAML + restart) needs no changes here."""
    return [
        SystemSummary(system_id=policy.system_id, display_name=policy.display_name)
        for policy in policy_store.all()
    ]


@router.post("", response_model=IntakeDiagnosisResponse)
async def submit_intake(
    intake: ComplaintIntake,
    intake_service: IntakeService = Depends(get_intake_service),
    diagnostic_service: DiagnosticService = Depends(get_diagnostic_service),
) -> IntakeDiagnosisResponse:
    assert_agent_not_killed()

    correlation_id = str(uuid.uuid4())
    request_model = await intake_service.submit(
        login_id=intake.login_id,
        intake=intake,
        correlation_id=correlation_id,
    )
    principal = Principal(sub=request_model.subject_sub)
    run_result = await diagnostic_service.run_diagnostic(request_model.id, principal)

    return IntakeDiagnosisResponse(
        diagnostic_request_id=str(request_model.id),
        correlation_id=correlation_id,
        message=build_verdict_message(run_result),
        run=run_result,
    )


@router.post("/{diagnostic_request_id}/escalate", response_model=EscalationResponse)
async def escalate_intake(
    diagnostic_request_id: uuid.UUID,
    escalation: EscalationRequest,
    diagnostic_service: DiagnosticService = Depends(get_diagnostic_service),
) -> EscalationResponse:
    """Follow-up for when a self_service_fix (or any) outcome didn't
    actually resolve the user's issue — hands the existing diagnosis to a
    human without re-running the funnel. See EscalationRequest."""
    assert_agent_not_killed()

    return await diagnostic_service.escalate_request(
        diagnostic_request_id, escalation.user_sub, escalation.note
    )
