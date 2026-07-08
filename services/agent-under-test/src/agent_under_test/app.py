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

from fastapi import FastAPI
from pydantic import BaseModel

from eeof_core.models import get_agent
from eeof_core.models.agent_catalog import agent_system_prompt
from eeof_core.providers import get_provider

AGENT_ID = "retirement-401k"

app = FastAPI(title="agent-under-test", version="0.1.0")


class ChatRequest(BaseModel):
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}]
    # Optional breach scenario (e.g. "advice_leak") — swaps in a guardrail-weakened
    # variant so the agent deterministically fails a guardrail judge. Demo-only.
    scenario: str | None = None


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
async def chat(req: ChatRequest) -> dict:
    provider = get_provider()
    # The final user message is the turn to answer; the rest is context.
    history = [
        {"role": "assistant" if m.get("role") == "agent" else m.get("role", "user"),
         "content": m.get("content", "")}
        for m in req.messages
    ]
    reply = await provider.chat(
        system=agent_system_prompt(AGENT_ID, req.scenario),
        messages=history or [{"role": "user", "content": "Hello"}],
        max_tokens=400,
        temperature=0.4,
    )
    return {"reply": reply, "agent": AGENT_ID}
