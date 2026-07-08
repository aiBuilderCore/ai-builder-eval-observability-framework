"""Cross-service contracts: auth context, the uniform Job, and the error envelope."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat().replace("+00:00", "Z")


class Principal(BaseModel):
    """Resolved from the bearer token by the orchestrator; never client-supplied."""

    subject: str = "alex@acme"
    tenant: str
    workspace: str


class JobState(StrEnum):
    queued = "queued"
    running = "running"
    finalizing = "finalizing"
    ready = "ready"
    shipped = "shipped"
    failed = "failed"


class JobProgress(BaseModel):
    done: int = 0
    total: int = 0
    phase: str = "queued"
    # Stage-specific counters (e.g. qgen cells/evolution/filter) surfaced to the
    # UI's detailed progress panels. Kept generic so the Job contract stays lean.
    detail: dict[str, Any] = Field(default_factory=dict)


class Job(BaseModel):
    """The uniform async job record shared by qgen/sim/eval/evidence."""

    job_id: str
    tenant: str
    workspace: str
    kind: str  # qgen.generate | simulation.run | evaluation.score | observability.evidence
    stage: str  # qgen | sim | eval | obs
    state: JobState = JobState.queued
    progress: JobProgress = Field(default_factory=JobProgress)
    idempotency_key: str | None = None
    config_hash: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None  # e.g. {"run_id": "sim_..."} once ready
    error: dict[str, Any] | None = None
    # Lifecycle audit trail: one {ts, state, by} per transition (queued →
    # running → ready/failed). Appended by the edge on submit and the worker on
    # each state change so every stage's job page can render a real timeline.
    events: list[dict[str, Any]] = Field(default_factory=list)
    submitted_by: str = "alex@acme"
    submitted_at: str = Field(default_factory=iso)
    updated_at: str = Field(default_factory=iso)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorBody
