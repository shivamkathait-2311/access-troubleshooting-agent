from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.core.vault import LeasedCredential
from app.remediation.tiers import Tier


@dataclass
class RemediationContext:
    """Threaded through playbook execute()/rollback(). Carries the separate,
    write-capable credential (see app/core/vault.py) loaded only
    post-approval by app/remediation/executor.py — never the read-only
    connector credential used during diagnosis."""

    subject_sub: str
    system_id: str
    write_credential: LeasedCredential
    correlation_id: str


class PlaybookBase(ABC):
    """Base class for an allow-listed remediation playbook."""

    id: str
    version: str
    tier: Tier

    @abstractmethod
    async def execute(self, ctx: RemediationContext) -> dict[str, Any]:
        """Perform the remediation action. Returns rollback data to persist
        on the RemediationActionModel (see app/models/remediation_action.py)."""
        raise NotImplementedError

    @abstractmethod
    async def rollback(self, ctx: RemediationContext, rollback_data: dict[str, Any]) -> None:
        """Undo the action using the captured rollback_data."""
        raise NotImplementedError


class PlaybookRegistry:
    """Playbooks are explicitly registered here, never dynamically
    discovered/imported — the allow-list is enforceable by code review, not
    convention."""

    def __init__(self) -> None:
        self._playbooks: dict[str, PlaybookBase] = {}

    def register(self, playbook: PlaybookBase) -> None:
        self._playbooks[playbook.id] = playbook

    def get(self, playbook_id: str) -> PlaybookBase:
        playbook = self._playbooks.get(playbook_id)
        if playbook is None:
            raise KeyError(f"Playbook '{playbook_id}' is not registered")
        return playbook
