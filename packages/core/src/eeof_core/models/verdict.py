"""Evaluation contracts — judges, juries, verdicts, verdict sets."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import iso


class JudgeDraft(BaseModel):
    name: str  # e.g. "helpfulness" or "customjudge.acme.tone"
    rubric: str = "helpfulness"
    kind: str = "builtin"  # builtin | byoj (bring-your-own-judge)
    prompt: str = ""
    config: dict[str, Any] = Field(default_factory=dict)


class Judge(JudgeDraft):
    id: str
    version: int = 1
    created_at: str = Field(default_factory=iso)

    @property
    def ref(self) -> str:
        return f"{self.name}@v{self.version}"


class JuryDraft(BaseModel):
    panel_id: str | None = None
    name: str
    judge_refs: list[str]  # "helpfulness@v1", …
    aggregation: str = "majority"  # majority | mean | veto


class Jury(JuryDraft):
    created_at: str = Field(default_factory=iso)


class EvalRequest(BaseModel):
    run_ids: list[str]
    judge_ids: list[str] = Field(default_factory=list)  # version-pinned refs
    panel_id: str | None = None
    mode: str = "panel"  # single | panel
    mitigations: list[str] = Field(default_factory=list)


class Verdict(BaseModel):
    id: str
    verdict_set_id: str
    run_id: str
    trace_id: str
    question_id: str
    judge_ref: str
    passed: bool
    score: float  # 0..1
    rationale: str = ""
    persona_id: str = ""
    persona_version: str = ""
    # UI-facing fields (verdict-set / executive-report screens).
    dimension: str = ""  # rubric dimension
    verdict: str = "pass"  # pass | fail | abstain
    question_prompt: str = ""
    persona_name: str = ""
    mode: str = "judge"  # judge | jury
    judges: list[dict[str, Any]] = Field(default_factory=list)  # per-juror scores
    consensus_rate: float | None = None
    mitigations_applied: list[str] = Field(default_factory=list)
    rubric: dict[str, Any] = Field(default_factory=dict)
    human_overridden: bool = False


class VerdictSet(BaseModel):
    id: str
    tenant: str
    workspace: str
    run_ids: list[str]
    judge_refs: list[str]
    aggregation: str = "majority"
    verdict_count: int = 0
    pass_rate: float = 0.0
    pass_count: int = 0
    aggregate_scores: dict[str, float] = Field(default_factory=dict)
    mode: str = "judge"
    created_at: str = Field(default_factory=iso)
    state: str = "shipped"
