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
        return data["choices"][0]["message"]["content"]
