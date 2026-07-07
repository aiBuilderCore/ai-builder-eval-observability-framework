"""Evaluation contracts — judges, juries, verdicts, verdict sets."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import iso


class JudgeDraft(BaseModel):
    name: str  # e.g. "helpfulness" or "customjudge.acme.tone"
    rubric: str = "helpfulness"  # dimension/rubric id scored under the hood
    kind: str = "builtin"  # builtin | byoj (bring-your-own-judge)
    prompt: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    # Catalog card metadata — opaque body, visible card (see the evaluation spec).
    # All optional so a bare draft (name + rubric) still validates; the built-in
    # catalog fills them in.
    label: str = ""  # display name, e.g. "Answer relevance"
    dimension: str = ""  # rubric dimension the card advertises
    family: str = "frontier-LLM"  # frontier-LLM | specialist-LLM | non-LLM
    turn_types: list[str] = Field(default_factory=lambda: ["single", "multi"])
    reference: str = "reference-free"  # reference-free | retrieval-context | golden | …
    cost: str = "$$"  # rough per-call cost band ($ / $$ / $$$)
    pattern: str = ""  # implementation pattern, e.g. "RAGAS claim decomposition"
    blurb: str = ""  # one-line what/why for the catalog card
    biases: list[str] = Field(default_factory=list)  # hardened-against bias tags
    threshold: float = 0.7  # default pass/fail cutoff
    pillar: str = ""  # quality pillar this judge scores (see judge_catalog.JUDGE_PILLARS)


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
    pillar: str = ""  # quality pillar of the scoring judge (denormalised for rollups)
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
