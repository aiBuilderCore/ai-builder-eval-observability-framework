"""Self-Heal contracts — the closed remediation loop that sits after Observability.

An Observability gate/drift breach opens a `SelfHealIncident`. It then walks the
same four-stage loop — gate (detect) → rca (diagnose) → simulate (rehearse) →
remediate (apply) — governed by a declarative `Policy`. Following the Arize
"closing the loop" model, a candidate `Fix` is a *missing capability* rehearsed
on real flagged traces and submitted WITH evidence (before/after metric vs the
gate, a confidence score vs the policy band, a reasoning summary). High-confidence
fixes auto-ship in-band; the rest escalate to a human who audits the
self-verification. All fields are synthetic in the demo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .common import iso

Stage = Literal["gate", "rca", "simulate", "remediate"]
Status = Literal["open", "escalated", "resolved"]
StepStatus = Literal["done", "active", "queued"]


class FixMetric(BaseModel):
    label: str
    baseline: str
    gate: str
    projected: str


class FixChange(BaseModel):
    before: str
    after: str


class Fix(BaseModel):
    """A candidate remediation submitted with its evidence, not just a diff."""

    change: FixChange
    metric: FixMetric
    quality: str = "±0"          # projected quality delta, points
    sessions: str = "0"          # flagged sessions shadow-replayed on real traces
    reasoning: str = ""          # why this is a missing capability, not "try harder"
    verified: str | None = None  # post-ship re-measure, set once resolved


class TimelineStep(BaseModel):
    stage: Stage
    status: StepStatus
    when: str
    note: str


class IncidentTrace(BaseModel):
    id: str
    agent: str
    intent: str
    meta: str


class SelfHealIncident(BaseModel):
    id: str
    glyph: str = "chat"          # UI icon key (retriever/prompt/tool/parser/finance/chat)
    agent: str
    failure: str
    dimension: str | None = None  # breached judge dimension → keys the remediation playbook
    pillars: list[str] = Field(default_factory=list)
    stage: Stage = "gate"
    age: str = ""
    status: Status = "open"
    dispo: str = ""              # human-readable disposition line
    dispo_class: str = "idle"    # run | warn | ok | idle (chip colour)
    policy: str | None = None
    band: float | None = None    # confidence band from the governing policy
    confidence: float | None = None
    action: str = ""             # registry actions, " · "-joined
    incident_from: str | None = None  # source monitor/incident id, if any
    timeline: list[TimelineStep] = Field(default_factory=list)
    fix: Fix | None = None
    traces: list[IncidentTrace] = Field(default_factory=list)
    baseline_trace: IncidentTrace | None = None  # a real PASSING trace for the same
    # judge, when one exists in the run — lets RCA contrast a good vs. flagged answer
    opened_at: str = Field(default_factory=iso)
    resolved_at: str | None = None  # stamped on auto-close/approve → feeds median MTTR


class Policy(BaseModel):
    """Declarative remediation policy — the ship-vs-escalate contract (Policy DSL).

    `dimensions` + `agent` are the *structured* scope the matcher reads (a policy
    governs a breach when the breached judge dimension is listed and the agent is
    unscoped or matches). `trigger`/`dsl` stay for human-readable display only —
    they are no longer substring-scanned for matching.
    """

    name: str
    trigger: str                 # human-readable summary, e.g. "hallucination > thr from support_agent"
    dimensions: list[str] = Field(default_factory=list)  # judge names/dimensions governed
    agent: str | None = None     # agent scope (case-insensitive substring); None => any agent
    band: float | None = None    # confidence threshold to auto-ship; None => always escalate
    always_ticket: bool = False  # regulated agents: human sign-off regardless of score
    notify: str = ""             # channel to notify on escalate/ticket
    dsl: list[str] = Field(default_factory=list)  # rendered source lines (with highlight spans)


class PolicyDraft(BaseModel):
    """Author-supplied fields for a new policy — the service derives `trigger`/`dsl`.

    Structured scope only; the ship-vs-escalate contract is `always_ticket` (human
    sign-off) XOR `band` (auto-ship threshold)."""

    name: str
    dimensions: list[str] = Field(default_factory=list)  # judge dimensions governed
    agent: str | None = None     # agent scope (case-insensitive substring); None => any
    band: float | None = None    # auto-ship confidence threshold; None => escalate
    always_ticket: bool = False  # human sign-off regardless of score
    notify: str = ""


class RemediationAction(BaseModel):
    """One entry in the fixed vocabulary of safe remediation actions."""

    id: str
    name: str


class SelfHealSummary(BaseModel):
    open_incidents: int = 0
    auto_resolved_24h: int = 0
    median_mttr: str = "—"
    active_policies: int = 0


class IncidentActionRequest(BaseModel):
    """Human-in-the-loop verdict on an escalated candidate fix."""

    action: Literal["approve", "ticket", "reject"]
    note: str = ""
