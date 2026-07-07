"""Model-provider interface.

Every heavy stage (question generation, user-simulator, judge scoring) talks to
a `ModelProvider`, never to a vendor SDK directly. Concrete providers wrap a
single vendor API — Anthropic, AWS Bedrock, Azure OpenAI — and are selected by
config. The deterministic `echo` provider implements the same interface so the
whole pipeline runs offline and reproducibly.

A real provider only has to implement `chat`. Judge `score` has a default that
prompts the model for a JSON verdict and parses it, so every backend gets
scoring for free.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import TypedDict

Message = dict  # {"role": "user"|"assistant", "content": str}


class ScoreResult(TypedDict):
    passed: bool
    score: float
    rationale: str


JUDGE_SYSTEM = (
    "You are an impartial evaluation judge for the rubric '{rubric}'. "
    "Grade the ASSISTANT RESPONSE to the USER PROMPT. "
    "Reply with ONLY a JSON object: "
    '{{"score": <0..1 float>, "passed": <bool>, "rationale": "<one sentence>"}}.'
)

_JSON = re.compile(r"\{.*\}", re.DOTALL)


class ModelProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        *,
        system: str,
        messages: list[Message],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """Return the assistant's text for one completion."""

    async def score(self, *, rubric: str, prompt: str, response: str) -> ScoreResult:
        raw = await self.chat(
            system=JUDGE_SYSTEM.format(rubric=rubric),
            messages=[
                {"role": "user", "content": f"USER PROMPT:\n{prompt}\n\nASSISTANT RESPONSE:\n{response}"}
            ],
            max_tokens=256,
            temperature=0.0,
        )
        return self._parse_score(raw)

    @staticmethod
    def _parse_score(raw: str) -> ScoreResult:
        m = _JSON.search(raw or "")
        if not m:
            return {"passed": False, "score": 0.0, "rationale": "unparseable judge output"}
        try:
            obj = json.loads(m.group(0))
            score = float(obj.get("score", 0.0))
            return {
                "passed": bool(obj.get("passed", score >= 0.5)),
                "score": max(0.0, min(1.0, score)),
                "rationale": str(obj.get("rationale", ""))[:500],
            }
        except (ValueError, TypeError):
            return {"passed": False, "score": 0.0, "rationale": "invalid judge JSON"}
