import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnostic_request import DiagnosticRequestModel
from app.models.diagnostic_run import DiagnosticRunModel


class DiagnosticRepository:
    """Data access for diagnostic requests and runs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_request(self, request: DiagnosticRequestModel) -> DiagnosticRequestModel:
        self.db.add(request)
        await self.db.flush()
        return request

    async def get_request(self, request_id: uuid.UUID) -> DiagnosticRequestModel | None:
        return await self.db.get(DiagnosticRequestModel, request_id)

    async def create_run(self, run: DiagnosticRunModel) -> DiagnosticRunModel:
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run(self, run_id: uuid.UUID) -> DiagnosticRunModel | None:
        return await self.db.get(DiagnosticRunModel, run_id)

    async def list_runs_for_request(self, request_id: uuid.UUID) -> list[DiagnosticRunModel]:
        result = await self.db.execute(
            select(DiagnosticRunModel).where(DiagnosticRunModel.request_id == request_id)
        )
        return list(result.scalars().all())
