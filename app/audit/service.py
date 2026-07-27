from app.audit.events import AuditEvent
from app.audit.siem_shipper import SiemShipper
from app.core.security import Principal
from app.models.audit_event import AuditEventModel
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditEventResponse, AuditQueryFilters


class AuditService:
    """Exposes only `record()` and `query()` — there is no update/delete
    method anywhere on this class, enforcing the audit trail's immutability
    at the API-surface level, not just via DB grants."""

    def __init__(self, repository: AuditRepository, siem_shipper: SiemShipper):
        self.repository = repository
        self.siem_shipper = siem_shipper

    async def record(self, event: AuditEvent) -> None:
        model = AuditEventModel(
            correlation_id=event.correlation_id,
            requester_sub=event.requester_sub,
            diagnostic_subject_sub=event.diagnostic_subject_sub,
            event_type=event.event_type.value,
            visibility_tier=event.visibility_tier.value,
            payload=event.payload,
        )
        await self.repository.append(model)
        await self.siem_shipper.ship(event)

    async def query(
        self, principal: Principal, filters: AuditQueryFilters
    ) -> list[AuditEventResponse]:
        """Row-level-security-scoped read. A self-service user (no helpdesk/
        iam_admin role) is always restricted to their own subject,
        regardless of what filters.subject_sub requests."""
        scoped_filters = filters
        if not (principal.has_role("helpdesk") or principal.has_role("iam_admin")):
            scoped_filters = filters.model_copy(update={"subject_sub": principal.sub})

        rows = await self.repository.query(scoped_filters)
        return [
            AuditEventResponse(
                id=str(row.id),
                correlation_id=row.correlation_id,
                requester_sub=row.requester_sub,
                diagnostic_subject_sub=row.diagnostic_subject_sub,
                event_type=row.event_type,
                visibility_tier=row.visibility_tier,
                payload=row.payload,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ]
