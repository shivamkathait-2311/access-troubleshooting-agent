from fastapi import APIRouter, Depends

from app.audit.service import AuditService
from app.core.security import Principal
from app.dependencies.auth import get_principal
from app.dependencies.services import get_audit_service
from app.schemas.audit import AuditEventResponse, AuditQueryFilters

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditEventResponse])
async def query_audit_events(
    correlation_id: str | None = None,
    subject_sub: str | None = None,
    event_type: str | None = None,
    principal: Principal = Depends(get_principal),
    audit_service: AuditService = Depends(get_audit_service),
) -> list[AuditEventResponse]:
    """Row-level-security-scoped: AuditService.query() restricts a
    self-service-user principal to their own subject regardless of the
    subject_sub filter passed here."""
    filters = AuditQueryFilters(
        correlation_id=correlation_id, subject_sub=subject_sub, event_type=event_type
    )
    return await audit_service.query(principal, filters)
