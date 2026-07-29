"""LLMDiagnosticOrchestrator (app/orchestrator/agent_loop.py) — driven by a
scripted fake LLMClient, no real OpenAI call. Covers: parity with the
deterministic orchestrator on a simple case, and every fail-closed path
(budget exhausted, raised exception, hallucinated primary_step, per-turn
tool-call budget) resolving to Outcome.ESCALATION rather than a raised
exception or a silent 'all clear'."""

from test_diagnostic_funnel import FakeConnector, _make_context

from app.connectors.types import (
    AccountStatus,
    EffectivePermission,
    RequiredPermission,
    UserStatusResult,
)
from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.tool_types import ToolCall, ToolMessage, ToolTurnResult
from app.orchestrator.agent_loop import LLMDiagnosticOrchestrator
from app.orchestrator.agent_schemas import DiagnosisAnswer
from app.orchestrator.verdicts import FunnelStep, Outcome, VerdictStatus


class _ScriptedLLMClient(LLMClient):
    """Returns pre-programmed ToolTurnResults in order, one per
    run_tool_turn call. Raises AssertionError if called more times than
    scripted, so a test's expectations about the number of turns are
    enforced."""

    def __init__(self, script: list[ToolTurnResult]):
        self._script = list(script)
        self.turn_histories: list[list[ToolMessage]] = []

    async def parse(self, *, model, system, user_message, response_model, max_tokens=1024):
        raise NotImplementedError

    async def complete(self, *, model, system, user_message, max_tokens=512) -> str:
        raise NotImplementedError

    async def run_tool_turn(
        self, *, model, system, user_message, tools, response_schema, history, max_tokens=2048
    ) -> ToolTurnResult:
        self.turn_histories.append(list(history))
        if not self._script:
            raise AssertionError("scripted LLM client ran out of turns")
        return self._script.pop(0)


class _RaisingLLMClient(LLMClient):
    async def parse(self, *, model, system, user_message, response_model, max_tokens=1024):
        raise NotImplementedError

    async def complete(self, *, model, system, user_message, max_tokens=512) -> str:
        raise NotImplementedError

    async def run_tool_turn(
        self, *, model, system, user_message, tools, response_schema, history, max_tokens=2048
    ) -> ToolTurnResult:
        raise RuntimeError("simulated LLM provider failure")


def _tool_call_turn(*names: str) -> ToolTurnResult:
    calls = [ToolCall(call_id=f"c{i}", name=name, arguments={}) for i, name in enumerate(names)]
    return ToolTurnResult(
        tool_calls=calls,
        transcript_entry=ToolMessage(role="assistant_tool_request", tool_calls=calls),
    )


def _final_answer_turn(primary_step: FunnelStep, stop_reason: str) -> ToolTurnResult:
    answer = DiagnosisAnswer(
        primary_step=primary_step, stop_reason=stop_reason, reasoning_summary="test reasoning"
    )
    return ToolTurnResult(final_answer_json=answer.model_dump_json())


async def test_agrees_with_deterministic_orchestrator_on_locked_account() -> None:
    connector = FakeConnector(
        user_status=UserStatusResult(status=AccountStatus.LOCKED, detail="locked")
    )
    ctx = _make_context(connector)
    llm_client = _ScriptedLLMClient(
        [
            _tool_call_turn("get_user_status"),
            _final_answer_turn(FunnelStep.ACCOUNT_STATUS, "found_explanation"),
        ]
    )

    result = await LLMDiagnosticOrchestrator(llm_client).run(ctx)

    # Same conclusion as tests/orchestrator/test_diagnostic_funnel.py's
    # test_locked_account_is_self_service_fix — different investigation
    # path (only one tool called, not the fixed step1->2 order), same
    # outcome, because cause_code/outcome are re-derived deterministically.
    assert result.step_verdicts[-1].step == FunnelStep.ACCOUNT_STATUS
    assert result.step_verdicts[-1].status == VerdictStatus.FAIL
    assert result.step_verdicts[-1].cause_code == "locked"
    assert result.outcome == Outcome.SELF_SERVICE_FIX
    assert result.escalated is False
    assert result.agent_trace is not None
    assert len(result.agent_trace) == 1
    assert result.agent_trace[0]["tool_name"] == "get_user_status"


async def test_primary_finding_always_last_regardless_of_investigation_order() -> None:
    connector = FakeConnector(
        user_status=UserStatusResult(status=AccountStatus.ACTIVE),
        required_permissions=[RequiredPermission(kind="role", name="Super Security Admin")],
        effective_permissions=[EffectivePermission(kind="role", name="Some Other Role")],
    )
    ctx = _make_context(connector)
    llm_client = _ScriptedLLMClient(
        [
            _tool_call_turn("get_user_status", "get_required_permissions"),
            _tool_call_turn("get_effective_permissions"),
            _final_answer_turn(FunnelStep.AUTHORIZATION, "found_explanation"),
        ]
    )

    result = await LLMDiagnosticOrchestrator(llm_client).run(ctx)

    assert result.step_verdicts[-1].step == FunnelStep.AUTHORIZATION
    assert result.step_verdicts[-1].cause_code == "missing_role"
    assert result.step_verdicts[0].step == FunnelStep.ACCOUNT_STATUS
    assert result.outcome == Outcome.ACCESS_GAP


async def test_all_checks_passed_still_escalates() -> None:
    connector = FakeConnector(user_status=UserStatusResult(status=AccountStatus.ACTIVE))
    ctx = _make_context(connector)
    llm_client = _ScriptedLLMClient(
        [
            _tool_call_turn("get_user_status"),
            _final_answer_turn(FunnelStep.ACCOUNT_STATUS, "all_checks_passed"),
        ]
    )

    result = await LLMDiagnosticOrchestrator(llm_client).run(ctx)

    assert result.step_verdicts[-1].status == VerdictStatus.PASS_
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True


async def test_fails_closed_when_turn_budget_exhausted() -> None:
    connector = FakeConnector()
    ctx = _make_context(connector)
    # Never produce a final answer — every turn just re-requests a tool,
    # for exactly the configured max, so the loop exhausts its budget.
    script = [
        _tool_call_turn("check_availability") for _ in range(settings.LLM_AGENT_MAX_TOOL_TURNS)
    ]
    llm_client = _ScriptedLLMClient(script)

    result = await LLMDiagnosticOrchestrator(llm_client).run(ctx)

    assert result.step_verdicts == []
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True
    assert result.agent_trace is not None
    assert len(result.agent_trace) == settings.LLM_AGENT_MAX_TOOL_TURNS


async def test_fails_closed_on_raised_exception() -> None:
    connector = FakeConnector()
    ctx = _make_context(connector)

    result = await LLMDiagnosticOrchestrator(_RaisingLLMClient()).run(ctx)

    assert result.step_verdicts == []
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True


async def test_fails_closed_on_hallucinated_primary_step() -> None:
    connector = FakeConnector(user_status=UserStatusResult(status=AccountStatus.LOCKED))
    ctx = _make_context(connector)
    # Only get_user_status (account_status) is ever called, but the model
    # claims authorization is the primary finding — never investigated.
    llm_client = _ScriptedLLMClient(
        [
            _tool_call_turn("get_user_status"),
            _final_answer_turn(FunnelStep.AUTHORIZATION, "found_explanation"),
        ]
    )

    result = await LLMDiagnosticOrchestrator(llm_client).run(ctx)

    assert result.step_verdicts == []
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True


async def test_fails_closed_when_per_turn_tool_call_budget_exceeded() -> None:
    connector = FakeConnector()
    ctx = _make_context(connector)
    too_many_names = ["check_availability"] * (settings.LLM_AGENT_MAX_TOOL_CALLS_PER_TURN + 1)
    llm_client = _ScriptedLLMClient([_tool_call_turn(*too_many_names)])

    result = await LLMDiagnosticOrchestrator(llm_client).run(ctx)

    assert result.step_verdicts == []
    assert result.outcome == Outcome.ESCALATION
    assert result.escalated is True
