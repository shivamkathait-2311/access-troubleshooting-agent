from enum import StrEnum

from pydantic import BaseModel, Field

from app.orchestrator.verdicts import DiagnosticRunResult


class ComplaintCategory(StrEnum):
    LOGIN_FAILURE = "login_failure"
    PERMISSION_DENIED = "permission_denied"
    LOCKED_ACCOUNT = "locked_account"
    OUTAGE = "outage"
    OTHER = "other"


class ComplaintIntake(BaseModel):

    login_id: str = Field(
        min_length=1,
        description=(
            "OpenIAM login/principal — e.g. "
            "'test.client22' — what they actually type to sign in, not the "
        ),
    )
    free_text: str = Field(description="The user's raw complaint, verbatim")
    system_id: str | None = Field(
        default=None,
        description=(
            "Which registered system this complaint is about — see GET /systems "
            "for valid values. Explicitly caller-supplied, never inferred/guessed "
            "by the LLM. Omit to fall back to settings.DEFAULT_SYSTEM_ID (today's "
            "single-system convenience, not a permanent default)."
        ),
    )


class DiagnosticRequestDraft(BaseModel):
    """The LLM intake parser's structured output schema.

    Produced by app/llm/intake_parser.py via client.parse() with this model
    as response_model — Pydantic validation is the enforcement boundary.
    This is a *draft*: services/intake_service.py re-derives the real
    `subject` from the validated token before constructing a DiagnosticRequest.
    `system_id` is deliberately NOT here — it's caller-supplied on
    ComplaintIntake, never LLM-inferred. See ComplaintIntake.system_id.
    """

    complaint_category: ComplaintCategory
    free_text_summary: str = Field(description="One-sentence normalized summary")
    mentioned_subject: str | None = Field(
        default=None,
        description="A username/email the complaint text mentions, if any — untrusted, advisory",
    )


class DiagnosticRequest(BaseModel):
    """The orchestrator's actual input: requester + subject always come from
    the validated Principal, never from LLM output."""

    correlation_id: str
    requester_sub: str
    subject_sub: str
    system_id: str
    complaint_category: ComplaintCategory
    free_text_summary: str


class IntakeDiagnosisResponse(BaseModel):
    """API response for POST /intake: the persisted request id plus the
    completed diagnostic run, in one round trip."""

    diagnostic_request_id: str
    correlation_id: str
    message: str
    run: DiagnosticRunResult


class EscalationRequest(BaseModel):
    """Body for POST /intake/{diagnostic_request_id}/escalate — a follow-up
    to an already-diagnosed request, e.g. when a self_service_fix outcome
    didn't actually resolve the user's problem. Does not re-run the
    funnel; just hands the existing diagnostic bundle to a human."""

    user_sub: str = Field(
        description=(
            "TEST ONLY: the escalating user's OpenIAM internal userId — used "
            "only for audit attribution (requester_sub), unrelated to "
            "ComplaintIntake.login_id (this endpoint doesn't re-run the "
            "funnel, so there's no subject to resolve)."
        )
    )
    note: str | None = Field(
        default=None,
        description="Optional free-text reason, e.g. 'the reset link didn't work'.",
    )


class EscalationResponse(BaseModel):
    """API response for POST /intake/{diagnostic_request_id}/escalate."""

    correlation_id: str
    message: str


class SystemSummary(BaseModel):
    """One entry in GET /systems — lets a caller (FE dropdown, Slack bot,
    etc.) discover valid ComplaintIntake.system_id values at request time,
    rather than hardcoding an enum. Reflects PolicyStore.all(), itself
    backed by the git-managed policy YAML files — no separate storage."""

    system_id: str
    display_name: str
