from pathlib import Path

from app.core.exceptions import NotFoundError
from app.policy.loader import load_policies
from app.policy.schema import SystemPolicy


class PolicyStore:
    """In-memory, read-only for the life of the process.

    Deliberately exposes no write/update method — this is the structural
    enforcement of "not editable via chat/API at runtime"; policy changes
    only happen via a Git PR + process restart, never through this class.
    """

    def __init__(self, policy_dir: Path):
        self._policies: dict[str, SystemPolicy] = load_policies(policy_dir)

    def get(self, system_id: str) -> SystemPolicy:
        policy = self._policies.get(system_id)
        if policy is None:
            raise NotFoundError(f"No policy registered for system_id '{system_id}'")
        return policy

    def has(self, system_id: str) -> bool:
        return system_id in self._policies

    def all(self) -> list[SystemPolicy]:
        return list(self._policies.values())
