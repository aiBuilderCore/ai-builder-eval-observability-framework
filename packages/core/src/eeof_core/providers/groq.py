"""Groq Chat Completions wrapper — OpenAI-compatible, called over REST with httpx.

Groq serves open-weight models (Llama 3.x, gpt-oss) behind the OpenAI Chat
Completions schema, so this is a thin `httpx` client with a Bearer key — no SDK
dependency. It is the default fallback for the Azure OpenAI GPT-4 primary: when
the Azure deployment credentials are absent or a call fails, the provider factory
routes here (see providers/__init__.py).
"""

from __future__ import annotations

import httpx

from ..config import settings
from .base import Message, ModelProvider


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
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self._url, headers=self._headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
