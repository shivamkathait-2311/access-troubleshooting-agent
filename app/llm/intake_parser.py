from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.prompts.intake_prompt import INTAKE_SYSTEM_PROMPT, build_intake_user_message
from app.schemas.intake import ComplaintIntake, DiagnosticRequestDraft


async def parse_complaint(
    client: LLMClient, intake: ComplaintIntake
) -> DiagnosticRequestDraft:
    """Single-shot, zero-tool-authority extraction of a free-text complaint
    into a schema-validated draft. The caller (app/services/intake_service.py)
    must re-derive the real subject from the validated Principal — never
    trust `mentioned_subject` on the returned draft.
    """
    return await client.parse(
        model=settings.OPENAI_INTAKE_MODEL,
        system=INTAKE_SYSTEM_PROMPT,
        user_message=build_intake_user_message(intake.free_text),
        response_model=DiagnosticRequestDraft,
    )
