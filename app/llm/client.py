import json
from abc import ABC, abstractmethod
from typing import TypeVar

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.core.config import settings
from app.llm.tool_types import ToolCall, ToolMessage, ToolSpec, ToolTurnResult

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """Provider-agnostic LLM interface. `parse` (structured extraction) and
    `complete` (plain text generation) are zero-tool-authority — no
    `**kwargs` passthrough, no `tools` parameter, fully enumerated
    signatures — used by app/llm/intake_parser.py and app/llm/explanation.py,
    neither of which ever gains tool authority.

    `run_tool_turn` is a deliberately separate, clearly-named third
    capability: the only method on this interface that can hand the model
    any tool authority at all. It exists solely for
    app/orchestrator/agent_loop.py's LLM diagnostic agent — intake_parser.py
    and explanation.py never call it and have no reason to.

    Call sites depend only on this abstract type and never know which
    concrete provider is active — that's resolved once, in
    app/dependencies/services.py.
    """

    @abstractmethod
    async def parse(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        response_model: type[T],
        max_tokens: int = 1024,
    ) -> T:
        """Structured extraction: returns an instance of `response_model`."""
        raise NotImplementedError

    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        max_tokens: int = 512,
    ) -> str:
        """Plain-text generation."""
        raise NotImplementedError

    @abstractmethod
    async def run_tool_turn(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        tools: list[ToolSpec],
        response_schema: type[BaseModel],
        history: list[ToolMessage],
        max_tokens: int = 2048,
    ) -> ToolTurnResult:
        """One turn of a tool-calling + structured-final-answer loop: sends
        system + user_message + `tools` + `history` (prior tool-call
        requests and their fed-back results) to the model. Returns either
        the ToolCall(s) it wants executed next, or its final answer (as a
        JSON string the caller validates against `response_schema` itself
        — this method never imports the caller's concrete schema type).
        The multi-turn loop, tool execution, and budget/timeout enforcement
        all live in the caller (app/orchestrator/agent_loop.py) — this
        method is a single request/response primitive, same level as
        parse()/complete().
        """
        raise NotImplementedError


class OpenAIClient(LLMClient):
    """LLMClient backed by OpenAI's Chat Completions API."""

    def __init__(self, api_key: str | None = None):
        self._client = AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    async def parse(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        response_model: type[T],
        max_tokens: int = 1024,
    ) -> T:
        """Structured extraction via client.chat.completions.parse()."""
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        response = await self._client.chat.completions.parse(
            model=model,
            max_completion_tokens=max_tokens,
            messages=messages,
            response_format=response_model,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI response did not include a parsed message")
        return parsed

    async def complete(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        max_tokens: int = 512,
    ) -> str:
        """Plain-text generation via client.chat.completions.create()."""
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        response = await self._client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content or ""

    async def run_tool_turn(
        self,
        *,
        model: str,
        system: str,
        user_message: str,
        tools: list[ToolSpec],
        response_schema: type[BaseModel],
        history: list[ToolMessage],
        max_tokens: int = 2048,
    ) -> ToolTurnResult:
        """One turn via client.chat.completions.parse(), which — unlike
        parse() above — is called with both `tools=` (so the model can
        request a tool call) and `response_format=` (so its eventual final
        answer is schema-validated), simultaneously. `history` is replayed
        in full every call, since the Chat Completions API is stateless
        per request."""
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        for entry in history:
            if entry.role == "assistant_tool_request":
                assert entry.tool_calls is not None
                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": call.call_id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": json.dumps(call.arguments),
                                },
                            }
                            for call in entry.tool_calls
                        ],
                    }
                )
            else:
                assert entry.tool_result is not None
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": entry.tool_result.call_id,
                        "content": entry.tool_result.content,
                    }
                )

        oa_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                    # OpenAI's chat.completions.parse() requires every tool
                    # to be "strict" when tools= is combined with
                    # response_format= (auto-parsing the final answer) —
                    # confirmed live: a non-strict tool raises ValueError
                    # before any request is even sent.
                    "strict": True,
                },
            }
            for tool in tools
        ]

        response = await self._client.chat.completions.parse(
            model=model,
            max_completion_tokens=max_tokens,
            messages=messages,
            tools=oa_tools,  # type: ignore[arg-type]
            tool_choice="auto",
            response_format=response_schema,
        )
        message = response.choices[0].message

        if message.tool_calls:
            calls = [
                ToolCall(
                    call_id=call.id,
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments or "{}"),
                )
                for call in message.tool_calls
            ]
            return ToolTurnResult(
                tool_calls=calls,
                transcript_entry=ToolMessage(role="assistant_tool_request", tool_calls=calls),
            )

        if message.parsed is None:
            raise ValueError(
                "OpenAI tool-turn response had neither tool_calls nor a parsed final answer"
            )
        return ToolTurnResult(final_answer_json=message.parsed.model_dump_json())
