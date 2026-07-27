from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_event import AuditEventModel
from app.schemas.audit import AuditQueryFilters


class AuditRepository:
    """Append-only data access. Deliberately exposes no update/delete —
    this is the last line of enforcement (alongside DB-level grants) for
    the audit trail's immutability requirement."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def append(self, event: AuditEventModel) -> AuditEventModel:
        self.db.add(event)
        await self.db.flush()
        return event

    async def query(self, filters: AuditQueryFilters) -> list[AuditEventModel]:
        stmt = select(AuditEventModel)
        if filters.correlation_id:
            stmt = stmt.where(AuditEventModel.correlation_id == filters.correlation_id)
        if filters.subject_sub:
            stmt = stmt.where(AuditEventModel.diagnostic_subject_sub == filters.subject_sub)
        if filters.event_type:
            stmt = stmt.where(AuditEventModel.event_type == filters.event_type)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
