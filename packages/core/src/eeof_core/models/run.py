"""Simulation contracts — adapters, runs, and trace refs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from .common import iso


class Transport(StrEnum):
    rest = "rest"
    mcp = "mcp"
    a2a = "a2a"


class AdapterDraft(BaseModel):
    name: str
    transport: Transport = Transport.rest
    config: dict[str, Any] = Field(default_factory=dict)  # endpoint, headers, agent card…


class Adapter(AdapterDraft):
    id: str
    version: int = 1
    created_at: str = Field(default_factory=iso)
    created_by: str = "alex@acme"
    smoke_ok: bool = True
    # Rich fields surfaced by the onboarding / registry UI.
    capabilities: dict[str, Any] = Field(default_factory=dict)
    smoke_test: dict[str, Any] = Field(default_factory=dict)
    transport_config: dict[str, Any] = Field(default_factory=dict)


class RunRequest(BaseModel):
    seed_set_id: str
    adapter_id: str
    mode: str = "auto"
    max_turns: int = 12
    concurrency: int = 32
    user_simulator_model: str = "claude-opus-4-8"


class Turn(BaseModel):
    role: str  # user | agent
    content: str
    ts: str = Field(default_factory=iso)


class TraceRef(BaseModel):
    id: str
    run_id: str
    question_id: str
    persona_id: str
    persona_version: str
    turns: int
    blob_uri: str = ""
    sha256: str = ""


class RunState(StrEnum):
    queued = "queued"
    warming = "warming"
    running = "running"
    finalizing = "finalizing"
    ready = "ready"
    failed = "failed"


class Run(BaseModel):
    id: str
    tenant: str
    workspace: str
    seed_set_id: str
    seed_set_question_count: int = 0
    adapter_snapshot: dict[str, Any]
    config_hash: str
    state: RunState = RunState.queued
    total_questions: int = 0
    completed: int = 0
    trace_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=iso)
    created_by: str = "alex@acme"
    completed_at: str | None = None
    failure_reason: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    # progress detail (conversations/turns/tokens/wallclock) + output summary.
    progress: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
