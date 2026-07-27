from pydantic import BaseModel

from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.prompts.explanation_prompt import (
    EXPLANATION_SYSTEM_PROMPT,
    build_explanation_user_message,
)
from app.orchestrator.verdicts import DiagnosticRunResult


class _RedactedVerdict(BaseModel):
    step: str
    status: str
    cause_code: str | None


class _RedactedRun(BaseModel):
    """The only shape ever sent to the LLM explanation layer. Deliberately
    excludes DiagnosticRunResult.password_reset_url (an OpenIAM login,
    embedded in a URL — a real user identifier) and every
    VerdictResult.detail (free-form, connector-specific text with no
    redaction guarantee) — see the design doc's LLM guardrails (4.3/4.5):
    hosted LLM calls only ever get pre-redacted structured verdicts, never
    raw diagnostic payloads."""

    correlation_id: str
    outcome: str
    escalated: bool
    step_verdicts: list[_RedactedVerdict]


def _redact(run: DiagnosticRunResult) -> _RedactedRun:
    return _RedactedRun(
        correlation_id=run.correlation_id,
        outcome=run.outcome.value,
        escalated=run.escalated,
        step_verdicts=[
            _RedactedVerdict(step=v.step.value, status=v.status.value, cause_code=v.cause_code)
            for v in run.step_verdicts
        ],
    )


async def explain_run(client: LLMClient, run: DiagnosticRunResult) -> str:
    """Single-shot, zero-tool-authority translation of redacted verdict
    codes into user-facing text. Only _redact(run)'s output — never the raw
    DiagnosticRunResult — is ever serialized into the prompt; see
    _RedactedRun for exactly what that includes.
    """
    return await client.complete(
        model=settings.OPENAI_EXPLANATION_MODEL,
        system=EXPLANATION_SYSTEM_PROMPT,
        user_message=build_explanation_user_message(_redact(run).model_dump_json()),
    )
