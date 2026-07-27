from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import PolicyValidationError
from app.policy.schema import SystemPolicy


def load_policies(policy_dir: Path) -> dict[str, SystemPolicy]:
    """Validate every *.yaml under policy_dir at process startup.

    Fail-fast: raises PolicyValidationError immediately on any bad document
    so a broken policy can never reach runtime. Called once from
    app.main's lifespan.
    """
    policies: dict[str, SystemPolicy] = {}

    for path in sorted(policy_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        try:
            policy = SystemPolicy.model_validate(raw)
        except PydanticValidationError as exc:
            raise PolicyValidationError(f"Invalid policy file {path.name}: {exc}") from exc

        if policy.system_id in policies:
            raise PolicyValidationError(
                f"Duplicate system_id '{policy.system_id}' in {path.name}"
            )
        policies[policy.system_id] = policy

    return policies
