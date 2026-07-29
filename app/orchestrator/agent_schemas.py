from typing import Literal

from pydantic import BaseModel, Field

from app.orchestrator.verdicts import FunnelStep


class DiagnosisAnswer(BaseModel):
    """The LLM agent's entire final structured output. Deliberately
    minimal: cause_code/detail for whichever step is named here are always
    re-derived deterministically by agent_loop.py from the same tool
    evidence the model already saw — never trusted from LLM output. This
    schema only carries the LLM's genuine judgment call: which check most
    directly explains the complaint, and why investigation stopped there.
    """

    primary_step: FunnelStep = Field(
        description="Which check most directly explains the user's complaint."
    )
    stop_reason: Literal["found_explanation", "all_checks_passed"] = Field(
        description=(
            "'found_explanation' if primary_step identifies a real problem; "
            "'all_checks_passed' if everything investigated came back clean "
            "and primary_step is just the last/most relevant thing checked."
        )
    )
    reasoning_summary: str = Field(
        max_length=500,
        description=(
            "1-3 sentences on why primary_step is the explanation. "
            "Audit-trail only — never shown to the end user or substituted "
            "into any user-facing message template."
        ),
    )
