"""agent-under-test — the demo 401(k) retirement-planning agent, served over REST.

This is the *target* the pipeline evaluates, not part of the eval control plane.
It exposes the minimal REST contract the simulation adapter speaks:

    POST /chat  { "messages": [{"role": "user"|"assistant", "content": str}, ...] }
             -> { "reply": str }

The reply is produced by the configured `ModelProvider` (Azure OpenAI GPT-4 by
default; the deterministic echo provider when no credentials are set), system-
prompted with the built-in agent's guardrails from `eeof_core.models.agent_catalog`.
The simulation service onboards this endpoint as a REST adapter, so a run drives
it turn-by-turn over the wire exactly as it would a customer's real agent.

Synthetic demo only — educational, never real financial advice.
"""

from __future__ import annotations

import hashlib
import time

from fastapi import FastAPI, Request
from pydantic import BaseModel

from eeof_core.models import get_agent
from eeof_core.models.agent_catalog import agent_system_prompt
from eeof_core.providers import get_provider

from .tracing import build_turn_spans, new_trace_id, parse_traceparent

AGENT_ID = "retirement-401k"

app = FastAPI(title="agent-under-test", version="0.1.0")


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}]
    # Optional breach scenario (e.g. "advice_leak") — swaps in a guardrail-weakened
    # variant so the agent deterministically fails a guardrail judge. Demo-only.
    scenario: str | None = None


# The agent's tool catalogue. Each tool is a named capability the planner calls
# to answer a 401(k) question. Selection is deterministic on the conversation so a
# run produces a real, reproducible tool-call sequence Observability can track
# (trajectory drift, tool-call monitors) — not a synthetic scalar. Every turn does
# realistic work even for terse follow-ups, so the sequence is never a bare
# one-tool stub. `scenario` (a guardrail-regressed variant) swaps the closing
# compliance step for a risky speculative projection — a clear, consistent
# trajectory divergence a monitor should catch, tied to the numeric_accuracy /
# no_financial_advice breach.
_DOMAIN_TOOLS = ("contribution_calculator", "account_type_advisor", "irs_limit_lookup", "risk_profiler")
_TOOL_DETAIL = {
    "retrieve_plan_docs": "401(k) summary plan description",
    "account_type_advisor": "roth vs traditional",
    "contribution_calculator": "employer match + deferral",
    "irs_limit_lookup": "402(g) elective deferral limit",
    "risk_profiler": "target-date glidepath",
    "compliance_disclosure": "no-advice + tax-year disclaimer",
    "speculative_projection": "unqualified return projection (guardrail breach)",
}


def _plan_tool_calls(convo_text: str, scenario: str | None) -> list[dict]:
    """Plan a realistic tool sequence from the whole conversation so far.

    Grounds on plan docs, adds the domain tools the conversation implies (falling
    back to a stable hash-seeded pair when the text is terse so every turn is a
    real 3–4 tool sequence), then closes with compliance — or, in the regressed
    scenario, a speculative projection instead.
    """
    text = (convo_text or "").lower()
    picked: list[str] = ["retrieve_plan_docs"]

    def add(name: str) -> None:
        if name not in picked:
            picked.append(name)

    if any(k in text for k in ("roth", "traditional", "pre-tax", "pretax", "after-tax")):
        add("account_type_advisor")
    if any(k in text for k in ("match", "%", "percent", "contribute", "contribution", "how much", "save")):
        add("contribution_calculator")
    if any(k in text for k in ("limit", "maximum", "max", "cap", "catch-up", "catch up")):
        add("irs_limit_lookup")
    if any(k in text for k in ("risk", "aggressive", "conservative", "allocation", "fund", "invest")):
        add("risk_profiler")

    # Terse turns (short follow-ups) still do real work: deterministically seed a
    # couple of domain tools from a stable hash of the conversation, so trajectory
    # sees varied but reproducible sequences instead of a lone retrieve_plan_docs.
    if len(picked) < 3:
        seed = int(hashlib.sha256((text or "x").encode()).hexdigest(), 16)
        for i in range(2):
            add(_DOMAIN_TOOLS[(seed + i) % len(_DOMAIN_TOOLS)])

    # Compliant agent always closes with a disclosure; the regressed variant
    # instead emits an unqualified projection — a consistent, catchable drift.
    picked.append("speculative_projection" if scenario else "compliance_disclosure")

    return [{"name": n, "ok": True, "detail": _TOOL_DETAIL.get(n, "")} for n in picked]


@app.get("/health")
async def health() -> dict:
    return {"service": "agent-under-test", "status": "ok", "agent": AGENT_ID}


@app.get("/")
async def info() -> dict:
    """Smoke-test target + a description of the agent under test."""
    agent = get_agent(AGENT_ID) or {}
    return {
        "agent": AGENT_ID,
        "name": agent.get("name", ""),
        "domain": agent.get("domain", ""),
        "guardrails": agent.get("guardrails", []),
        "provider": get_provider().name,
    }


@app.post("/chat")
async def chat(req: ChatRequest, request: Request) -> dict:
    provider = get_provider()
    # The final user message is the turn to answer; the rest is context.
    history = [
        {"role": "assistant" if m.get("role") == "agent" else m.get("role", "user"),
         "content": m.get("content", "")}
        for m in req.messages
    ]
    # Plan from the whole conversation so far (not just the last, possibly terse,
    # follow-up) so every turn produces a realistic, context-grounded sequence.
    convo_text = " ".join(
        m.get("content", "") for m in req.messages if m.get("role") in (None, "user")
    )
    # Continue the run's trace when the caller propagates W3C `traceparent` (so
    # every turn of a simulation shares one trace id); start a fresh trace
    # otherwise. The propagated span becomes the root AGENT span's parent.
    trace_id, parent_span_id = parse_traceparent(request.headers.get("traceparent"))
    trace_id = trace_id or new_trace_id()

    # Plan the real tool-call sequence for this turn, measure the prompt render
    # and the model call, then assemble the OpenInference span tree.
    t_prompt = time.monotonic()
    system_prompt = agent_system_prompt(AGENT_ID, req.scenario)
    prompt_ms = int((time.monotonic() - t_prompt) * 1000)
    tool_calls = _plan_tool_calls(convo_text, req.scenario)

    t_llm = time.monotonic()
    reply = await provider.chat(
        system=system_prompt,
        messages=history or [{"role": "user", "content": "Hello"}],
        max_tokens=400,
        temperature=0.4,
    )
    llm_ms = int((time.monotonic() - t_llm) * 1000)

    spans = build_turn_spans(
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        convo_text=convo_text,
        reply=reply,
        tool_calls=tool_calls,
        model_name=provider.name,
        llm_ms=llm_ms,
        prompt_ms=prompt_ms,
    )
    return {
        "reply": reply,
        "agent": AGENT_ID,
        "tool_calls": tool_calls,
        "trace_id": trace_id,
        "spans": spans,
    }
