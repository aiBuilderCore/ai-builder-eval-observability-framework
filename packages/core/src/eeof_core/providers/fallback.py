"""Fallback chain — try an ordered list of providers until one succeeds.

Wraps N concrete providers (e.g. Azure OpenAI GPT-4 → Groq → echo). Each `chat`
call walks the chain in order; if a provider raises (network error, rate limit,
auth failure) the next one is tried. The last link is always the deterministic
`echo` provider, so a call never hard-fails as long as the chain is non-empty.

Only *ready* providers are placed in the chain (see providers/__init__.py), so a
missing Azure deployment simply means Groq becomes the effective primary.
"""

from __future__ import annotations

import sys

from .base import Message, ModelProvider


class FallbackProvider(ModelProvider):
    def __init__(self, chain: list[ModelProvider]) -> None:
        if not chain:
            raise ValueError("FallbackProvider needs at least one provider")
        self._chain = chain
        self.name = "fallback(" + " → ".join(p.name for p in chain) + ")"
        # model_label of the link that served the most recent call. Provenance
        # code reads this so a score is attributed to the model that produced it
        # (possibly the echo safety net when the primary was rate-limited), not
        # the statically-configured effective primary.
        self.last_served_label = self.model_label

    @property
    def model_label(self) -> str:
        # Attribute verdicts to the effective primary — the first link that isn't
        # the offline echo safety net (falls back to it if that's all there is).
        for provider in self._chain:
            if provider.name != "echo":
                return provider.model_label
        return self._chain[0].model_label

    async def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        last_err: Exception | None = None
        for i, provider in enumerate(self._chain):
            try:
                out = await provider.chat(
                    system=system,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                self.last_served_label = provider.model_label
                return out
            except Exception as e:  # noqa: BLE001 — deliberately broad: any failure falls through
                last_err = e
                nxt = self._chain[i + 1].name if i + 1 < len(self._chain) else "none"
                print(
                    f"[providers] '{provider.name}' failed ({type(e).__name__}: {e}); "
                    f"falling back to '{nxt}'.",
                    file=sys.stderr,
                )
        # Exhausted the chain (only possible if every non-echo link failed and
        # echo was not present). Re-raise the last error for visibility.
        raise last_err if last_err else RuntimeError("empty fallback chain")
