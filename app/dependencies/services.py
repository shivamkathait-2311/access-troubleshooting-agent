from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import AuditService
from app.audit.siem_shipper import SiemShipper
from app.connectors.registry import ConnectorRegistry
from app.core.config import settings
from app.core.vault import VaultClient
from app.db.session import get_db
from app.llm.client import LLMClient, OpenAIClient
from app.orchestrator.state_machine import DiagnosticOrchestrator
from app.policy.store import PolicyStore
from app.remediation.approval import ApprovalGate
from app.remediation.executor import RemediationExecutor
from app.remediation.playbook import PlaybookRegistry
from app.repositories.audit_repository import AuditRepository
from app.repositories.diagnostic_repository import DiagnosticRepository
from app.repositories.remediation_repository import RemediationRepository
from app.services.diagnostic_service import DiagnosticService
from app.services.intake_service import IntakeService
from app.services.remediation_service import RemediationService

# ---- App-lifetime singletons (built once in app.main's lifespan, stashed on
# app.state; these dependencies just read them back out). ----


def get_policy_store(request: Request) -> PolicyStore:
    return request.app.state.policy_store  # type: ignore[no-any-return]


def get_connector_registry(request: Request) -> ConnectorRegistry:
    return request.app.state.connector_registry  # type: ignore[no-any-return]


def get_playbook_registry(request: Request) -> PlaybookRegistry:
    return request.app.state.playbook_registry  # type: ignore[no-any-return]


# ---- Per-call clients ----


def get_llm_client() -> LLMClient:
    return OpenAIClient()


def get_vault_client() -> VaultClient:
    return VaultClient(addr=settings.VAULT_ADDR, role=settings.VAULT_ROLE)


def get_siem_shipper() -> SiemShipper:
    return SiemShipper()


def get_approval_gate() -> ApprovalGate:
    return ApprovalGate()


def get_diagnostic_orchestrator() -> DiagnosticOrchestrator:
    return DiagnosticOrchestrator()


# ---- Repositories ----


def get_diagnostic_repository(db: AsyncSession = Depends(get_db)) -> DiagnosticRepository:
    return DiagnosticRepository(db)


def get_remediation_repository(db: AsyncSession = Depends(get_db)) -> RemediationRepository:
    return RemediationRepository(db)


def get_audit_repository(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


# ---- Services ----


def get_audit_service(
    repository: AuditRepository = Depends(get_audit_repository),
    siem_shipper: SiemShipper = Depends(get_siem_shipper),
) -> AuditService:
    return AuditService(repository, siem_shipper)


def get_intake_service(
    llm_client: LLMClient = Depends(get_llm_client),
    repository: DiagnosticRepository = Depends(get_diagnostic_repository),
    audit: AuditService = Depends(get_audit_service),
    policy_store: PolicyStore = Depends(get_policy_store),
    connector_registry: ConnectorRegistry = Depends(get_connector_registry),
) -> IntakeService:
    return IntakeService(llm_client, repository, audit, policy_store, connector_registry)


def get_diagnostic_service(
    policy_store: PolicyStore = Depends(get_policy_store),
    connector_registry: ConnectorRegistry = Depends(get_connector_registry),
    orchestrator: DiagnosticOrchestrator = Depends(get_diagnostic_orchestrator),
    repository: DiagnosticRepository = Depends(get_diagnostic_repository),
    audit: AuditService = Depends(get_audit_service),
) -> DiagnosticService:
    return DiagnosticService(policy_store, connector_registry, orchestrator, repository, audit)


def get_remediation_executor(
    registry: PlaybookRegistry = Depends(get_playbook_registry),
    vault: VaultClient = Depends(get_vault_client),
    approval_gate: ApprovalGate = Depends(get_approval_gate),
    repository: RemediationRepository = Depends(get_remediation_repository),
    audit: AuditService = Depends(get_audit_service),
) -> RemediationExecutor:
    return RemediationExecutor(registry, vault, approval_gate, repository, audit)


def get_remediation_service(
    executor: RemediationExecutor = Depends(get_remediation_executor),
    repository: RemediationRepository = Depends(get_remediation_repository),
) -> RemediationService:
    return RemediationService(executor, repository)
