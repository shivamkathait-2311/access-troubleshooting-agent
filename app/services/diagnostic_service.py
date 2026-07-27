import uuid
from datetime import UTC, datetime
from typing import Any

from app.audit.events import AuditEvent, AuditEventType, VisibilityTier
from app.audit.service import AuditService
from app.connectors.registry import ConnectorRegistry
from app.core.exceptions import NotFoundError
from app.core.security import Principal
from app.models.diagnostic_run import DiagnosticRunModel
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.state_machine import DiagnosticOrchestrator
from app.orchestrator.verdict_messages import build_escalation_message
from app.orchestrator.verdicts import DiagnosticRunResult, FunnelStep
from app.policy.store import PolicyStore
from app.repositories.diagnostic_repository import DiagnosticRepository
from app.schemas.intake import DiagnosticRequest, DiagnosticRequestDraft, EscalationResponse


class DiagnosticService:
    """Resolves a persisted request into a DiagnosticContext, runs the
    orchestrator, and persists + audits the result."""

    def __init__(
        self,
        policy_store: PolicyStore,
        connector_registry: ConnectorRegistry,
        orchestrator: DiagnosticOrchestrator,
        repository: DiagnosticRepository,
        audit: AuditService,
    ):
        self.policy_store = policy_store
        self.connector_registry = connector_registry
        self.orchestrator = orchestrator
        self.repository = repository
        self.audit = audit

    async def run_diagnostic(
        self, request_id: uuid.UUID, principal: Principal
    ) -> DiagnosticRunResult:
        request_model = await self.repository.get_request(request_id)
        if request_model is None:
            raise NotFoundError(f"Diagnostic request {request_id} not found")

        draft = DiagnosticRequestDraft.model_validate(request_model.parsed_draft)
        request = DiagnosticRequest(
            correlation_id=request_model.correlation_id,
            requester_sub=request_model.requester_sub,
            subject_sub=request_model.subject_sub,
            system_id=request_model.system_id,
            complaint_category=draft.complaint_category,
            free_text_summary=draft.free_text_summary,
        )

        policy = self.policy_store.get(request.system_id)
        connector_config = {
            **policy.connector.model_dump(mode="json"),
            "health_endpoint": policy.health_endpoint,
            "role_permission_map": [
                mapping.model_dump(mode="json") for mapping in policy.role_permission_map
            ],
        }
        connector = self.connector_registry.get_connector(
            policy.system_id, policy.connector.type, connector_config
        )
        ctx = DiagnosticContext(
            request=request,
            principal=principal,
            connector=connector,
            correlation_id=request.correlation_id,
        )

        result = await self.orchestrator.run(ctx)

        run_model = DiagnosticRunModel(
            request_id=request_model.id,
            correlation_id=result.correlation_id,
            step_verdicts=[v.model_dump(mode="json") for v in result.step_verdicts],
            outcome=result.outcome.value,
            escalated=result.escalated,
            password_reset_url=result.password_reset_url,
        )
        await self.repository.create_run(run_model)

        await self.audit.record(
            AuditEvent(
                correlation_id=result.correlation_id,
                requester_sub=principal.sub,
                diagnostic_subject_sub=request.subject_sub,
                event_type=AuditEventType.DIAGNOSTIC_RUN_COMPLETED,
                visibility_tier=VisibilityTier.SELF_SERVICE_USER,
                payload=result.model_dump(mode="json"),
                occurred_at=datetime.now(UTC),
            )
        )

        if result.escalated:
            # Log-only stub: no ITSM integration yet (see plan doc Phase 4).
            # The full diagnostic bundle in the payload is what a real
            # ticket would attach.
            await self.audit.record(
                AuditEvent(
                    correlation_id=result.correlation_id,
                    requester_sub=principal.sub,
                    diagnostic_subject_sub=request.subject_sub,
                    event_type=AuditEventType.ESCALATION_CREATED,
                    visibility_tier=VisibilityTier.SELF_SERVICE_USER,
                    payload=result.model_dump(mode="json"),
                    occurred_at=datetime.now(UTC),
                )
            )

        return result

    async def escalate_request(
        self, request_id: uuid.UUID, user_sub: str, note: str | None
    ) -> EscalationResponse:
        """User-triggered escalation of an already-diagnosed request — e.g.
        a self_service_fix outcome that didn't actually resolve the issue.
        Does not re-run the funnel; just hands the existing bundle (if any)
        to a human via the audit trail, same as an auto-escalation."""
        request_model = await self.repository.get_request(request_id)
        if request_model is None:
            raise NotFoundError(f"Diagnostic request {request_id} not found")

        runs = await self.repository.list_runs_for_request(request_id)
        latest_run = max(runs, key=lambda r: r.started_at) if runs else None

        # Which of the 4 named scenarios this was — read back from the
        # *original* diagnosis's last step/cause, not re-detected here.
        last_step: FunnelStep | None = None
        cause_code: str | None = None
        if latest_run is not None and latest_run.step_verdicts:
            last_verdict = latest_run.step_verdicts[-1]
            last_step = FunnelStep(last_verdict["step"])
            cause_code = last_verdict.get("cause_code")

        payload: dict[str, Any] = {
            "note": note,
            "escalation_reason": "user_requested",
            "scenario": last_step.value if last_step is not None else None,
        }
        if latest_run is not None:
            payload["step_verdicts"] = latest_run.step_verdicts
            payload["outcome"] = latest_run.outcome

        await self.audit.record(
            AuditEvent(
                correlation_id=request_model.correlation_id,
                requester_sub=user_sub,
                diagnostic_subject_sub=request_model.subject_sub,
                event_type=AuditEventType.ESCALATION_CREATED,
                visibility_tier=VisibilityTier.SELF_SERVICE_USER,
                payload=payload,
                occurred_at=datetime.now(UTC),
            )
        )

        password_reset_url = latest_run.password_reset_url if latest_run is not None else None
        message = build_escalation_message(
            last_step, cause_code, password_reset_url, request_model.correlation_id
        )

        return EscalationResponse(correlation_id=request_model.correlation_id, message=message)
