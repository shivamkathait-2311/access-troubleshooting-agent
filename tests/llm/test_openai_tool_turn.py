"""OpenAIClient.run_tool_turn()'s message-translation plumbing — mocks
AsyncOpenAI's chat.completions.parse(), no live network call. See
app/llm/client.py."""

import json
from unittest.mock import AsyncMock, patch

from pydantic import BaseModel

from app.llm.client import OpenAIClient
from app.llm.tool_types import ToolCall, ToolMessage, ToolResult, ToolSpec


class _Answer(BaseModel):
    value: str


def _tool_spec() -> ToolSpec:
    return ToolSpec(
        name="check_availability",
        description="Check system availability",
        parameters_schema={"type": "object", "properties": {}, "required": []},
    )


def _make_client() -> OpenAIClient:
    return OpenAIClient(api_key="test-key")


class _FakeToolCallFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.function = _FakeToolCallFunction(name, arguments)


class _FakeMessage:
    def __init__(self, tool_calls=None, parsed=None):
        self.tool_calls = tool_calls
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, message: _FakeMessage):
        self.message = message


class _FakeResponse:
    def __init__(self, message: _FakeMessage):
        self.choices = [_FakeChoice(message)]


async def test_run_tool_turn_returns_tool_calls_when_model_requests_them() -> None:
    client = _make_client()
    fake_message = _FakeMessage(
        tool_calls=[_FakeToolCall("call-1", "check_availability", "{}")]
    )
    fake_parse = AsyncMock(return_value=_FakeResponse(fake_message))

    with patch.object(client._client.chat.completions, "parse", fake_parse):
        result = await client.run_tool_turn(
            model="gpt-4o-mini",
            system="sys",
            user_message="user",
            tools=[_tool_spec()],
            response_schema=_Answer,
            history=[],
        )

    assert result.final_answer_json is None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].call_id == "call-1"
    assert result.tool_calls[0].name == "check_availability"
    assert result.transcript_entry is not None
    assert result.transcript_entry.role == "assistant_tool_request"

    # Verify the tools= payload sent to OpenAI matches our schema.
    _, kwargs = fake_parse.call_args
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Check system availability",
                "parameters": {"type": "object", "properties": {}, "required": []},
                "strict": True,
            },
        }
    ]
    assert kwargs["tool_choice"] == "auto"
    assert kwargs["response_format"] is _Answer


async def test_run_tool_turn_returns_final_answer_when_model_is_done() -> None:
    client = _make_client()
    fake_message = _FakeMessage(tool_calls=None, parsed=_Answer(value="done"))
    fake_parse = AsyncMock(return_value=_FakeResponse(fake_message))

    with patch.object(client._client.chat.completions, "parse", fake_parse):
        result = await client.run_tool_turn(
            model="gpt-4o-mini",
            system="sys",
            user_message="user",
            tools=[_tool_spec()],
            response_schema=_Answer,
            history=[],
        )

    assert result.tool_calls == []
    assert result.final_answer_json is not None
    assert json.loads(result.final_answer_json) == {"value": "done"}


async def test_run_tool_turn_replays_history_into_messages() -> None:
    client = _make_client()
    fake_message = _FakeMessage(tool_calls=None, parsed=_Answer(value="done"))
    fake_parse = AsyncMock(return_value=_FakeResponse(fake_message))

    history = [
        ToolMessage(
            role="assistant_tool_request",
            tool_calls=[ToolCall(call_id="call-1", name="check_availability", arguments={})],
        ),
        ToolMessage(
            role="tool_result",
            tool_result=ToolResult(
                call_id="call-1", name="check_availability", content='{"status": "up"}'
            ),
        ),
    ]

    with patch.object(client._client.chat.completions, "parse", fake_parse):
        await client.run_tool_turn(
            model="gpt-4o-mini",
            system="sys",
            user_message="user",
            tools=[_tool_spec()],
            response_schema=_Answer,
            history=history,
        )

    _, kwargs = fake_parse.call_args
    messages = kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "sys"}
    assert messages[1] == {"role": "user", "content": "user"}
    assert messages[2]["role"] == "assistant"
    assert messages[2]["tool_calls"][0]["id"] == "call-1"
    assert messages[2]["tool_calls"][0]["function"]["name"] == "check_availability"
    assert messages[3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": '{"status": "up"}',
    }
