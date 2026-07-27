from datetime import UTC, datetime

from app.audit.events import AuditEvent, AuditEventType, VisibilityTier
from app.audit.service import AuditService
from app.connectors.registry import ConnectorRegistry
from app.core.config import settings
from app.core.exceptions import LoginNotFoundError
from app.llm.client import LLMClient
from app.llm.intake_parser import parse_complaint
from app.models.diagnostic_request import DiagnosticRequestModel
from app.policy.store import PolicyStore
from app.repositories.diagnostic_repository import DiagnosticRepository
from app.schemas.intake import ComplaintIntake


class IntakeService:
    """Turns a raw complaint into a persisted DiagnosticRequestModel.

    Security-critical: the persisted `subject_sub` always comes from
    resolving `intake.login_id` against the target system's own connector
    (ConnectorSPI.resolve_subject_sub), never from the LLM draft's
    `mentioned_subject` — a login with no match raises LoginNotFoundError
    before any LLM call or persistence happens, rather than silently
    diagnosing the wrong (or no) account.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        repository: DiagnosticRepository,
        audit: AuditService,
        policy_store: PolicyStore,
        connector_registry: ConnectorRegistry,
    ):
        self.llm_client = llm_client
        self.repository = repository
        self.audit = audit
        self.policy_store = policy_store
        self.connector_registry = connector_registry

    async def submit(
        self,
        login_id: str,
        intake: ComplaintIntake,
        correlation_id: str,
    ) -> DiagnosticRequestModel:
        # system_id is caller-supplied (see ComplaintIntake.system_id), never
        # LLM-inferred — resolved up front, before spending an LLM call on a
        # request that can't resolve to a real system (or a real user)
        # anyway. PolicyStore.get raises NotFoundError for an unknown
        # system_id.
        system_id = intake.system_id or settings.DEFAULT_SYSTEM_ID
        policy = self.policy_store.get(system_id)
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

        subject_sub = await connector.resolve_subject_sub(login_id)
        if subject_sub is None:
            raise LoginNotFoundError(f"No user found for login id '{login_id}'")

        draft = await parse_complaint(self.llm_client, intake)

        request_model = DiagnosticRequestModel(
            correlation_id=correlation_id,
            requester_sub=subject_sub,
            subject_sub=subject_sub,
            system_id=system_id,
            raw_complaint_text=intake.free_text,
            parsed_draft=draft.model_dump(mode="json"),
        )
        await self.repository.create_request(request_model)

        await self.audit.record(
            AuditEvent(
                correlation_id=correlation_id,
                requester_sub=subject_sub,
                diagnostic_subject_sub=subject_sub,
                event_type=AuditEventType.DIAGNOSTIC_REQUEST_RECEIVED,
                visibility_tier=VisibilityTier.SELF_SERVICE_USER,
                payload={"system_id": system_id, "category": draft.complaint_category.value},
                occurred_at=datetime.now(UTC),
            )
        )

        return request_model
