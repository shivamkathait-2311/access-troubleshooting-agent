"""explain_run() must never leak password_reset_url or any VerdictResult.detail
into the prompt sent to the (hosted) LLM — see app/llm/explanation.py's
_redact(). No live OpenAI call: LLMClient is faked and just captures what
it was given."""

from datetime import UTC, datetime

from app.llm.client import LLMClient
from app.llm.explanation import explain_run
from app.orchestrator.verdicts import (
    DiagnosticRunResult,
    FunnelStep,
    Outcome,
    VerdictResult,
    VerdictStatus,
)


class _CapturingLLMClient(LLMClient):
    def __init__(self) -> None:
        self.last_user_message: str | None = None

    async def parse(self, *, model, system, user_message, response_model, max_tokens=1024):
        raise NotImplementedError

    async def complete(self, *, model, system, user_message, max_tokens=512) -> str:
        self.last_user_message = user_message
        return "a friendly explanation"


def _locked_run_with_sensitive_fields() -> DiagnosticRunResult:
    return DiagnosticRunResult(
        correlation_id="corr-123",
        step_verdicts=[
            VerdictResult(
                step=FunnelStep.ACCOUNT_STATUS,
                status=VerdictStatus.FAIL,
                cause_code="locked",
                detail="OpenIAM status=ACTIVE secondaryStatus=LOCKED",
                source_connector_id="openiam",
                evaluated_at=datetime.now(UTC),
            )
        ],
        outcome=Outcome.SELF_SERVICE_FIX,
        escalated=False,
        password_reset_url="https://qa422.openiam.com/idp/auth-select?login=aaa",
    )


async def test_explain_run_never_sends_password_reset_url() -> None:
    client = _CapturingLLMClient()
    await explain_run(client, _locked_run_with_sensitive_fields())

    assert client.last_user_message is not None
    assert "password_reset_url" not in client.last_user_message
    assert "login=aaa" not in client.last_user_message
    assert "qa422.openiam.com" not in client.last_user_message


async def test_explain_run_never_sends_verdict_detail() -> None:
    client = _CapturingLLMClient()
    await explain_run(client, _locked_run_with_sensitive_fields())

    assert client.last_user_message is not None
    assert "detail" not in client.last_user_message
    assert "secondaryStatus" not in client.last_user_message


async def test_explain_run_still_sends_the_llm_safe_fields() -> None:
    client = _CapturingLLMClient()
    await explain_run(client, _locked_run_with_sensitive_fields())

    assert client.last_user_message is not None
    for expected in (
        "correlation_id",
        "corr-123",
        "outcome",
        "self_service_fix",
        "escalated",
        "step",
        "account_status",
        "status",
        "fail",
        "cause_code",
        "locked",
    ):
        assert expected in client.last_user_message
