"""Provider registry. `get_provider()` returns the configured backend singleton."""

from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import ModelProvider, ScoreResult
from .echo import EchoProvider


@lru_cache
def get_provider() -> ModelProvider:
    kind = settings.model_provider
    if kind == "echo":
        return EchoProvider()
    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if kind == "bedrock":
        from .bedrock import BedrockProvider

        return BedrockProvider()
    if kind == "azure_openai":
        from .azure_openai import AzureOpenAIProvider

        return AzureOpenAIProvider()
    raise ValueError(f"unknown MODEL_PROVIDER: {kind}")


__all__ = ["ModelProvider", "ScoreResult", "EchoProvider", "get_provider"]
