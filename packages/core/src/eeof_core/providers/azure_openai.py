"""Azure OpenAI Chat Completions wrapper — called over REST with httpx.

No SDK dependency: Azure OpenAI is a plain REST endpoint, so this works with the
core `httpx` dependency alone.
"""

from __future__ import annotations

import httpx

from ..config import settings
from .base import Message, ModelProvider


class AzureOpenAIProvider(ModelProvider):
    name = "azure_openai"

    def __init__(self) -> None:
        if not (settings.azure_openai_endpoint and settings.azure_openai_api_key
                and settings.azure_openai_deployment):
            raise RuntimeError(
                "MODEL_PROVIDER=azure_openai needs AZURE_OPENAI_ENDPOINT, "
                "AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT"
            )
        self._url = (
            f"{settings.azure_openai_endpoint.rstrip('/')}/openai/deployments/"
            f"{settings.azure_openai_deployment}/chat/completions"
            f"?api-version={settings.azure_openai_api_version}"
        )
        self._headers = {"api-key": settings.azure_openai_api_key}

    async def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        payload = {
            "messages": ([{"role": "system", "content": system}] if system else [])
            + [{"role": m["role"], "content": m["content"]} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self._url, headers=self._headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Azure content filtering can return HTTP 200 with a *null* (or empty)
        # completion and finish_reason="content_filter" — notably when authoring
        # adversarial red-team prompts. Unlike a network error this raises nothing,
        # so the fallback chain (→ Groq → echo) would never engage and the caller
        # would get a blank/broken message. Detect it and raise so the chain moves
        # on, exactly as it does for a transport failure.
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(
                f"azure_openai returned no choices (prompt_filter={data.get('prompt_filter_results')})"
            )
        finish = choices[0].get("finish_reason")
        content = (choices[0].get("message") or {}).get("content")
        if not content or not content.strip():
            raise RuntimeError(
                f"azure_openai returned empty content (finish_reason={finish!r}) — "
                "likely a content filter or refusal; falling through the provider chain."
            )
        return content
