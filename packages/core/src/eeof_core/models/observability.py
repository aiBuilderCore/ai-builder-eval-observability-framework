"""Observability contracts — monitors, incidents, evidence packs, deploy gate."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import iso


class MonitorDraft(BaseModel):
    name: str
    env: str = "staging"  # staging | prod
    rubric: str = "helpfulness"
    judge_ref: str = "helpfulness@v1"
    threshold: float = 0.8
    sample_rate: float = 0.1


class Monitor(MonitorDraft):
    id: str
    version: int = 1
    signed: bool = True
    created_at: str = Field(default_factory=iso)


class Incident(BaseModel):
    id: str
    monitor_id: str
    state: str = "open"  # open | ack | resolved
    severity: str = "medium"
    summary: str = ""
    opened_at: str = Field(default_factory=iso)


class TraceEvent(BaseModel):
    """One finished conversation, streamed on trace.events.<run_id>."""

    run_id: str
    trace_id: str
    question_id: str
    persona_id: str
    persona_version: str
    turns: int
    tokens: int = 0
    latency_ms: int = 0
    blob_uri: str = ""


class Batch(BaseModel):
    run_id: str
    tenant: str
    traces: int = 0
    tokens: int = 0
    first_seen: str = Field(default_factory=iso)
    last_seen: str = Field(default_factory=iso)


class GateDecision(BaseModel):
    candidate: str
    decision: str  # pass | fail | no_data
    pass_rate: float = 0.0
    threshold: float = 0.8
    verdict_set_ids: list[str] = Field(default_factory=list)
    evaluated_at: str = Field(default_factory=iso)
    # Optional baseline comparison — when a baseline verdict set is supplied the
    # gate is a real head-to-head, exposing the baseline pass_rate and the delta.
    baseline: str | None = None
    baseline_pass_rate: float | None = None
    delta: float | None = None


class EvidenceRequest(BaseModel):
    candidate: str
    verdict_set_ids: list[str] = Field(default_factory=list)
    title: str = "Evaluation evidence pack"


class EvidencePack(BaseModel):
    id: str
    tenant: str
    candidate: str
    title: str
    verdict_set_ids: list[str]
    gate: dict[str, Any] = Field(default_factory=dict)
    supersedes: str | None = None
    issued_at: str = Field(default_factory=iso)
    blob_uri: str = ""
    sha256: str = ""
