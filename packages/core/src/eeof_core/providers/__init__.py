"""Provider registry. `get_provider()` returns the configured backend singleton.

The backend is a *fallback chain*: the primary `MODEL_PROVIDER`, then the
`MODEL_FALLBACK` backend, then the offline `echo` provider. Any link whose
credentials are absent is dropped, so the chain adapts to what is configured —
with Azure creds blank and a Groq key set, Groq becomes the effective primary and
`echo` the safety net. A single-link chain is returned unwrapped.
"""

from __future__ import annotations

import sys
from functools import lru_cache

from ..config import settings
from .base import ModelProvider, ScoreResult
from .echo import EchoProvider


def _build(kind: str) -> ModelProvider | None:
    """Construct one provider, or return None when it is not usable/configured."""
    try:
        if kind == "echo":
            return EchoProvider()
        if kind == "anthropic":
            if not settings.anthropic_api_key:
                return None
            from .anthropic_provider import AnthropicProvider

            return AnthropicProvider()
        if kind == "bedrock":
            from .bedrock import BedrockProvider

            return BedrockProvider()
        if kind == "azure_openai":
            if not settings.azure_openai_ready:
                return None
            from .azure_openai import AzureOpenAIProvider

            return AzureOpenAIProvider()
        if kind == "groq":
            if not settings.groq_ready:
                return None
            from .groq import GroqProvider

            return GroqProvider()
    except Exception as e:  # noqa: BLE001 — a broken optional backend must not crash boot
        print(f"[providers] could not init '{kind}': {type(e).__name__}: {e}", file=sys.stderr)
        return None
    raise ValueError(f"unknown model provider: {kind}")


@lru_cache
def get_provider() -> ModelProvider:
    # Ordered, de-duplicated chain: primary → fallback → echo safety net.
    order: list[str] = [settings.model_provider]
    if settings.model_fallback and settings.model_fallback not in order:
        order.append(settings.model_fallback)
    if "echo" not in order:
        order.append("echo")

    chain = [p for kind in order if (p := _build(kind)) is not None]
    if not chain:  # nothing configured resolved — echo always constructs, but be safe
        chain = [EchoProvider()]

    if chain[0].name != settings.model_provider:
        print(
            f"[providers] primary '{settings.model_provider}' unavailable — "
            f"serving from '{chain[0].name}'.",
            file=sys.stderr,
        )
    if len(chain) == 1:
        return chain[0]

    from .fallback import FallbackProvider

    return FallbackProvider(chain)


__all__ = ["ModelProvider", "ScoreResult", "EchoProvider", "get_provider"]
