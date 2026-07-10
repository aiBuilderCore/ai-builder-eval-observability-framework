"""Groq Chat Completions wrapper — OpenAI-compatible, called over REST with httpx.

Groq serves open-weight models (Llama 3.x, gpt-oss) behind the OpenAI Chat
Completions schema, so this is a thin `httpx` client with a Bearer key — no SDK
dependency. It is the default fallback for the Azure OpenAI GPT-4 primary: when
the Azure deployment credentials are absent or a call fails, the provider factory
routes here (see providers/__init__.py).
"""

from __future__ import annotations

import asyncio
import random

import httpx

from ..config import settings
from .base import Message, ModelProvider

# Transient statuses worth retrying on the same provider before the fallback
# chain gives up and drops to echo. 429 = rate limit (Groq free tier bursts),
# 503 = temporarily overloaded.
#
# Bounded on purpose: a *few* short retries recover the occasional 429 (so most
# content is real), but sustained throttling falls through to echo quickly rather
# than sitting out Groq's rate-limit window call-after-call, which would push a
# single job past the seed pipeline's poll timeout. Fast-and-fully-real needs a
# paid/Azure key; on the free tier this trades a little content fidelity for a
# bootstrap that always finishes promptly.
_RETRY_STATUSES = frozenset({429, 503})
_MAX_ATTEMPTS = 3      # 1 initial + 2 retries
_BASE_DELAY = 0.4      # seconds; exponential: 0.4, 0.8 (+jitter)
_MAX_DELAY = 3.0       # cap any single backoff wait
_MAX_RETRY_AFTER = 4.0  # honor Retry-After only up to this; longer => drop to echo


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    """The server's requested wait (Groq sends fractional seconds), raw/uncapped.
    None if absent or unparseable. The caller decides whether the hint is short
    enough to honour or long enough to abandon in favour of the echo fallback."""
    raw = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class GroqProvider(ModelProvider):
    name = "groq"

    def __init__(self) -> None:
        if not settings.groq_ready:
            raise RuntimeError("MODEL_PROVIDER/fallback=groq needs GROQ_API_KEY (and GROQ_MODEL)")
        self._url = f"{settings.groq_endpoint.rstrip('/')}/chat/completions"
        self._model = settings.groq_model
        self._headers = {"Authorization": f"Bearer {settings.groq_api_key}"}

    async def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": m["role"], "content": m["content"]} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Retry transient rate-limit/overload responses on Groq itself instead of
        # instantly dropping to echo — a short backoff clears the occasional 429.
        # But if the server asks us to wait longer than _MAX_RETRY_AFTER, don't:
        # bail to echo now rather than sit out a long window call-after-call.
        async with httpx.AsyncClient(timeout=60) as client:
            for attempt in range(_MAX_ATTEMPTS):
                resp = await client.post(self._url, headers=self._headers, json=payload)
                if resp.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                    hinted = _retry_after_seconds(resp)
                    if hinted is not None and hinted > _MAX_RETRY_AFTER:
                        break  # long throttle → give up, let the chain use echo
                    backoff = min(_BASE_DELAY * (2**attempt), _MAX_DELAY)
                    delay = hinted if hinted is not None else backoff + random.uniform(0, 0.25)
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()  # non-retryable, or retries exhausted → chain drops to echo
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        # Reached only when we broke out on a long-throttle 429: surface it so the
        # FallbackProvider moves on to echo.
        raise httpx.HTTPStatusError(
            "groq rate-limited beyond retry budget", request=resp.request, response=resp
        )
