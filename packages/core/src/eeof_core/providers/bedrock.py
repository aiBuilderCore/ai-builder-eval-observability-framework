"""AWS Bedrock Converse API wrapper. Requires `boto3` (extra: infra).

boto3 is synchronous, so calls are offloaded to a thread to stay async-friendly.
"""

from __future__ import annotations

import asyncio

from ..config import settings
from .base import Message, ModelProvider


class BedrockProvider(ModelProvider):
    name = "bedrock"

    def __init__(self) -> None:
        try:
            import boto3
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("MODEL_PROVIDER=bedrock needs `uv sync --group infra`") from e
        kwargs: dict = {"region_name": settings.bedrock_region}
        if settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        self._client = boto3.client("bedrock-runtime", **kwargs)
        self._model_id = settings.bedrock_model_id

    async def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        def _call() -> str:
            resp = self._client.converse(
                modelId=self._model_id,
                system=[{"text": system}] if system else [],
                messages=[
                    {"role": m["role"], "content": [{"text": m["content"]}]} for m in messages
                ],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            parts = resp["output"]["message"]["content"]
            return "".join(p.get("text", "") for p in parts)

        return await asyncio.to_thread(_call)
