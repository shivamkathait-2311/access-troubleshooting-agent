import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.remediation_action import RemediationActionModel


class RemediationRepository:
    """Data access for remediation actions. Writes only — this repository
    has no delete method; superseding an action means recording a new one,
    never mutating history."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_action(self, action: RemediationActionModel) -> RemediationActionModel:
        self.db.add(action)
        await self.db.flush()
        return action

    async def get_action(self, action_id: uuid.UUID) -> RemediationActionModel | None:
        return await self.db.get(RemediationActionModel, action_id)

    async def update_status(self, action_id: uuid.UUID, status: str) -> None:
        action = await self.get_action(action_id)
        if action is None:
            raise ValueError(f"Remediation action {action_id} not found")
        action.status = status
        await self.db.flush()
