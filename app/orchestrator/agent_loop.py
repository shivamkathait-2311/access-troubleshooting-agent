import asyncio
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import logger_adapter
from app.llm.client import LLMClient
from app.llm.prompts.diagnostic_agent_prompt import (
    DIAGNOSTIC_AGENT_SYSTEM_PROMPT,
    build_diagnostic_agent_user_message,
)
from app.llm.tool_types import ToolMessage, ToolResult
from app.orchestrator.agent_schemas import DiagnosisAnswer
from app.orchestrator.agent_tools import TOOL_TO_STEP, build_agent_tools
from app.orchestrator.context import DiagnosticContext
from app.orchestrator.outcome_policy import resolve_outcome
from app.orchestrator.steps import (
    step1_system_availability,
    step2_account_status,
    step3_auth_events,
    step4_authorization,
)
from app.orchestrator.verdicts import (
    PASSWORD_RESET_ELIGIBLE_CAUSES,
    DiagnosticRunResult,
    FunnelStep,
    Outcome,
    VerdictResult,
)

# Same 4 steps, same funnel order, as state_machine.py's _STEP_NAMES — used
# here only to (a) re-run the real deterministic classifier for whichever
# steps the agent investigated, and (b) order the audit trail's
# non-primary verdicts predictably. Step 5 (path/infrastructure) has no
# tool and can never be investigated by this orchestrator either.
_STEP_MODULES: dict[
    FunnelStep, Callable[[DiagnosticContext], Awaitable[VerdictResult]]
] = {
    FunnelStep.SYSTEM_AVAILABILITY: step1_system_availability.run,
    FunnelStep.ACCOUNT_STATUS: step2_account_status.run,
    FunnelStep.AUTH_EVENTS: step3_auth_events.run,
    FunnelStep.AUTHORIZATION: step4_authorization.run,
}
_STEP_ORDER = (
    FunnelStep.SYSTEM_AVAILABILITY,
    FunnelStep.ACCOUNT_STATUS,
    FunnelStep.AUTH_EVENTS,
    FunnelStep.AUTHORIZATION,
)


class AgentTraceEntry(BaseModel):
    """One tool call + its redacted result, for the audit trail. Not sent
    to the model — this is bookkeeping the orchestrator keeps for itself."""

    turn: int
    tool_name: str
    tool_call_id: str
    redacted_result: str


class LLMDiagnosticOrchestrator:
    """LLM-agentic alternative to DiagnosticOrchestrator (state_machine.py):
    the LLM decides which of the 6 fixed, zero-argument tools to call, in
    what order, and when it has enough evidence, instead of walking
    step1->2->3->4 in fixed order. Implements the same contract as
    DiagnosticOrchestratorProtocol — DiagnosticService doesn't know or care
    which implementation it was given.

    Fail-closed identically to state_machine.py: any LLM error, timeout,
    hallucinated step reference, or exhausted tool-call budget becomes an
    empty-step_verdicts INCONCLUSIVE result -> Outcome.ESCALATION, never a
    raised exception, never a silent "all clear". `cause_code`/`detail` for
    the reported step are always re-derived from the real deterministic
    step module, never trusted from the LLM's own output — see
    _build_result.
    """

    def __init__(self, llm_client: LLMClient):
        self._llm_client = llm_client

    async def run(self, ctx: DiagnosticContext) -> DiagnosticRunResult:
        trace: list[AgentTraceEntry] = []
        investigated: set[FunnelStep] = set()

        try:
            answer = await asyncio.wait_for(
                self._converse(ctx, trace, investigated),
                timeout=settings.LLM_AGENT_RUN_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed by design, same
            # pattern as state_machine.py's _run_step_fail_closed.
            logger_adapter.error(
                "LLM diagnostic agent failed; converting to INCONCLUSIVE",
                correlation_id=ctx.correlation_id,
                error=str(exc),
            )
            return self._inconclusive(ctx, trace)

        if answer is None or answer.primary_step not in investigated:
            # Budget exhausted without a final answer, or the model named a
            # step it never actually called a tool for — a hallucination,
            # not a diagnosis.
            return self._inconclusive(ctx, trace)

        return await self._build_result(ctx, answer, trace, investigated)

    async def _converse(
        self,
        ctx: DiagnosticContext,
        trace: list[AgentTraceEntry],
        investigated: set[FunnelStep],
    ) -> DiagnosisAnswer | None:
        tool_specs, dispatch = build_agent_tools(ctx)
        history: list[ToolMessage] = []
        user_message = build_diagnostic_agent_user_message(ctx)

        for turn in range(settings.LLM_AGENT_MAX_TOOL_TURNS):
            result = await self._llm_client.run_tool_turn(
                model=settings.OPENAI_DIAGNOSTIC_MODEL,
                system=DIAGNOSTIC_AGENT_SYSTEM_PROMPT,
                user_message=user_message,
                tools=tool_specs,
                response_schema=DiagnosisAnswer,
                history=history,
            )

            if result.final_answer_json is not None:
                return DiagnosisAnswer.model_validate_json(result.final_answer_json)

            if len(result.tool_calls) > settings.LLM_AGENT_MAX_TOOL_CALLS_PER_TURN:
                raise ValueError("Model exceeded the per-turn tool-call budget")

            if result.transcript_entry is not None:
                history.append(result.transcript_entry)

            tool_results = []
            for call in result.tool_calls:
                content = await dispatch(call)
                step = TOOL_TO_STEP.get(call.name)
                if step is not None:
                    investigated.add(step)
                trace.append(
                    AgentTraceEntry(
                        turn=turn,
                        tool_name=call.name,
                        tool_call_id=call.call_id,
                        redacted_result=content,
                    )
                )
                tool_results.append(
                    ToolResult(call_id=call.call_id, name=call.name, content=content)
                )
            history.extend(ToolMessage(role="tool_result", tool_result=r) for r in tool_results)

        return None  # budget exhausted without a final answer

    async def _build_result(
        self,
        ctx: DiagnosticContext,
        answer: DiagnosisAnswer,
        trace: list[AgentTraceEntry],
        investigated: set[FunnelStep],
    ) -> DiagnosticRunResult:
        # Re-run the real, tested classifier for every step actually
        # investigated — never the LLM's own account of why. Ordered by
        # the normal funnel order for a predictable audit trail; the
        # primary finding always goes last regardless of that order, since
        # verdict_messages.py and DiagnosticService.escalate_request both
        # read step_verdicts[-1] as "the" verdict.
        verdicts: dict[FunnelStep, VerdictResult] = {}
        for step in _STEP_ORDER:
            if step in investigated:
                verdicts[step] = await _STEP_MODULES[step](ctx)

        primary = verdicts[answer.primary_step]
        others = [
            verdicts[step]
            for step in _STEP_ORDER
            if step in verdicts and step != answer.primary_step
        ]
        step_verdicts = [*others, primary]

        outcome = resolve_outcome(primary.step, primary.status, primary.cause_code)
        reset_eligible = (
            primary.step,
            primary.cause_code or "",
        ) in PASSWORD_RESET_ELIGIBLE_CAUSES

        return DiagnosticRunResult(
            correlation_id=ctx.correlation_id,
            step_verdicts=step_verdicts,
            outcome=outcome,
            escalated=outcome == Outcome.ESCALATION,
            password_reset_url=ctx.subject_password_reset_url if reset_eligible else None,
            agent_trace=[entry.model_dump(mode="json") for entry in trace],
        )

    def _inconclusive(
        self, ctx: DiagnosticContext, trace: list[AgentTraceEntry]
    ) -> DiagnosticRunResult:
        # Empty step_verdicts is an already-supported case: build_verdict_message
        # and DiagnosticService.escalate_request both guard for it explicitly.
        return DiagnosticRunResult(
            correlation_id=ctx.correlation_id,
            step_verdicts=[],
            outcome=Outcome.ESCALATION,
            escalated=True,
            password_reset_url=None,
            agent_trace=[entry.model_dump(mode="json") for entry in trace],
        )
