from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolSpec(BaseModel):
    """One callable tool's schema, as advertised to the model. Every tool
    in this codebase has an empty parameter schema — see
    app/orchestrator/agent_tools.py — the model never supplies any
    argument to any tool; it can only decide whether/when to call it."""

    name: str
    description: str
    parameters_schema: dict[str, Any]


class ToolCall(BaseModel):
    """One tool invocation the model requested this turn."""

    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The executed result of one ToolCall, to feed back to the model.
    `content` is a JSON-serialized, already-redacted payload — built by
    app/orchestrator/agent_tools.py, never raw connector output."""

    call_id: str
    name: str
    content: str


class ToolMessage(BaseModel):
    """One provider-agnostic transcript entry. The orchestrator accumulates
    these in a plain list and resends the whole list every turn — mirrors
    the OpenAI Chat Completions API being stateless per request."""

    role: Literal["assistant_tool_request", "tool_result"]
    tool_calls: list[ToolCall] | None = None  # set iff role == assistant_tool_request
    tool_result: ToolResult | None = None  # set iff role == tool_result


class ToolTurnResult(BaseModel):
    """What one call to LLMClient.run_tool_turn produced. Exactly one of
    tool_calls / final_answer_json is meaningful: either the model wants
    tools executed next, or it has a final answer for the caller to
    validate against its own response_schema (kept as a raw JSON string
    here, not a parsed model, since LLMClient is provider-agnostic and
    shouldn't need to know the caller's specific Pydantic type)."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    final_answer_json: str | None = None
    transcript_entry: ToolMessage | None = None  # set iff tool_calls is non-empty
