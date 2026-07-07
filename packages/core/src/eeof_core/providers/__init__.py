"""Provider registry. `get_provider()` returns the configured backend singleton."""

from __future__ import annotations

import sys
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
        # Default backend (GPT-4). If the deployment credentials aren't set,
        # degrade gracefully to the deterministic echo provider so a
        # from-scratch checkout / bootstrap still runs fully offline.
        if not settings.azure_openai_ready:
            print(
                "[providers] MODEL_PROVIDER=azure_openai but AZURE_OPENAI_ENDPOINT/"
                "_API_KEY/_DEPLOYMENT are not all set — falling back to the offline "
                "'echo' provider. Set them in .env to use real GPT-4.",
                file=sys.stderr,
            )
            return EchoProvider()
        from .azure_openai import AzureOpenAIProvider

        return AzureOpenAIProvider()
    raise ValueError(f"unknown MODEL_PROVIDER: {kind}")


__all__ = ["ModelProvider", "ScoreResult", "EchoProvider", "get_provider"]
