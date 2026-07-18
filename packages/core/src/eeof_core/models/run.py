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
    created_by: str = "nitin@acme"
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
    # Real tool calls the agent made on this turn (agent turns only), captured
    # from the agent-under-test's /chat response. Each entry: {name, ok, detail?}.
    # This is the genuine tool-call telemetry Observability's trajectory drift and
    # tool-call monitors read — not a synthesised scalar.
    tool_calls: list[dict] = Field(default_factory=list)
    # Real OpenInference span tree the agent emitted for this turn (agent turns
    # only): AGENT root + PROMPT/LLM/TOOL/RETRIEVER/GUARDRAIL children, with W3C
    # ids and OTel GenAI semconv attributes. `start_ms`/`duration_ms` are relative
    # to the turn; the simulation worker offsets them onto the conversation
    # timeline. Empty when the target exposes no instrumented endpoint.
    spans: list[dict] = Field(default_factory=list)


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
    created_by: str = "nitin@acme"
    completed_at: str | None = None
    failure_reason: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    # progress detail (conversations/turns/tokens/wallclock) + output summary.
    progress: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
