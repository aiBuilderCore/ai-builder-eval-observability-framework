"""Anthropic Messages API wrapper. Requires `anthropic` (extra: llm)."""

from __future__ import annotations

from ..config import settings
from .base import Message, ModelProvider


class AnthropicProvider(ModelProvider):
    name = "anthropic"

    def __init__(self) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("MODEL_PROVIDER=anthropic needs `uv sync --group llm`") from e
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.model_name

    async def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        resp = await self._client.messages.create(
            model=self._model,
            system=system,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return "".join(block.text for block in resp.content if block.type == "text")
