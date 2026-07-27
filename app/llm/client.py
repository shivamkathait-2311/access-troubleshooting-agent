from abc import ABC, abstractmethod
from typing import TypeVar

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)


class LLMClient(ABC):
    """Provider-agnostic LLM interface exposing exactly two operations:
    `parse` (structured extraction) and `complete` (plain text generation).

    Both signatures are fully enumerated on every implementation — there is
    no `**kwargs` passthrough and no `tools` parameter anywhere. This is
    the structural enforcement of "zero tool authority" for both the
    intake parser and the explanation layer: it is not possible for a
    caller to smuggle a `tools=` argument through any implementation, even
    by mistake.

    Call sites (app/llm/intake_parser.py, app/llm/explanation.py) depend
    only on this abstract type and never know which concrete provider is
    active — that's resolved once, in app/dependencies/services.py, from
    settings.LLM_PROVIDER.
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
