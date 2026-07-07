"""Synthetic seed for Self-Heal — incidents, policies, and the action registry.

Demo-grade, fully fabricated. Seeded into the data plane on service startup
(idempotent) the same way simulation-svc lazily seeds its built-in adapters. The
incident agent names match the evaluated agents in `eeof_core.seed_demo` so each
incident corresponds to a real quality breach; the quality rollup itself is
derived (not seeded) by `eeof_core.rollups`.
"""

from __future__ import annotations

# ── Remediation registry — the fixed vocabulary of safe actions ──────────────
SEED_ACTIONS: list[dict] = [
    {"id": "prompt_rewrite", "name": "Prompt rewrite"},
    {"id": "rerank_tune", "name": "Re-rank tune"},
    {"id": "guardrail_tweak", "name": "Guardrail tweak"},
    {"id": "fallback", "name": "Fall-back"},
    {"id": "kb_update", "name": "KB update"},
    {"id": "circuit_break", "name": "Circuit break"},
]

# ── Policy DSL — declarative ship-vs-escalate contracts ──────────────────────
SEED_POLICIES: list[dict] = [
    {
        "name": "client_assist_v3",
        "trigger": "hallucination_rate > 0.10 from support_agent",
        "band": 0.85,
        "always_ticket": False,
        "notify": "#ai-quality",
        "dsl": [
            '<span class="k">policy</span> <span class="s">"client_assist_v3"</span> {',
            '  <span class="k">on</span> hallucination_rate &gt; <span class="n">0.10</span> <span class="k">from</span> support_agent',
            '  <span class="k">diagnose with</span> rca_agent <span class="k">and</span> simulate',
            '  <span class="k">if</span> confidence &gt;= <span class="n">0.85</span> <span class="k">then</span> ship_fix',
            '  <span class="k">else</span> open_ticket <span class="k">and</span> notify <span class="s">"#ai-quality"</span>',
            "}",
        ],
    },
    {
        "name": "rag_quality_v2",
        "trigger": "context_overflow_rate > 0.02 from knowledge_search",
        "band": 0.80,
        "always_ticket": False,
        "notify": "#ai-quality",
        "dsl": [
            '<span class="k">policy</span> <span class="s">"rag_quality_v2"</span> {',
            '  <span class="k">on</span> context_overflow_rate &gt; <span class="n">0.02</span> <span class="k">from</span> knowledge_search',
            '  <span class="k">diagnose with</span> rca_agent <span class="k">and</span> simulate',
            '  <span class="k">if</span> confidence &gt;= <span class="n">0.80</span> <span class="k">then</span> apply(<span class="s">"re-rank tune"</span>)',
            '  <span class="k">else</span> escalate',
            "}",
        ],
    },
    {
        "name": "finance_guardrail_v1",
        "trigger": "no_financial_advice_breach > 0.005 from retirement_401k",
        "band": None,
        "always_ticket": True,
        "notify": "#compliance",
        "dsl": [
            '<span class="k">policy</span> <span class="s">"finance_guardrail_v1"</span> {',
            '  <span class="k">on</span> no_financial_advice_breach &gt; <span class="n">0.005</span> <span class="k">from</span> retirement_401k',
            '  <span class="k">diagnose with</span> rca_agent <span class="k">and</span> simulate',
            '  <span class="k">always</span> open_ticket <span class="k">and</span> notify <span class="s">"#compliance"</span>',
            "}",
        ],
    },
]

# ── Incidents — each walks gate → rca → simulate → remediate ─────────────────
SEED_INCIDENTS: list[dict] = [
    {
        "id": "INC-992", "glyph": "retriever", "agent": "Internal Knowledge Search",
        "failure": "Context window overflow", "pillars": ["Reliability", "Explainability"],
        "stage": "remediate", "age": "10 mins ago", "status": "open",
        "dispo": "Auto-remediating · shipping in-band", "dispo_class": "run",
        "policy": "rag_quality_v2", "band": 0.80, "confidence": 0.94,
        "action": "KB update · Re-rank tune",
        "timeline": [
            {"stage": "gate", "status": "done", "when": "10 mins ago", "note": "Reliability judge fired: 6.1% of retrievals exceeded the 8k-token context budget, breaching the 2% guardrail."},
            {"stage": "rca", "status": "done", "when": "9 mins ago", "note": "Root cause traced to an un-chunked knowledge-base upload that pushed average passage length +340%. No re-ranking cap was applied."},
            {"stage": "simulate", "status": "done", "when": "6 mins ago", "note": "Shadow-replayed 1,200 flagged sessions with a 512-token chunk cap + top-5 re-rank. Projected overflow 0.3%, quality +2.1 pts, confidence 0.94."},
            {"stage": "remediate", "status": "active", "when": "4 mins ago", "note": "0.94 ≥ 0.80 band → auto-shipping in-band. Applied chunking policy v3 and re-indexed; re-measuring the guardrail to confirm close."},
        ],
        "fix": {
            "change": {"before": "chunking: none · re-rank: off · avg passage ≈ 1,700 tok", "after": "chunking: 512 tok · re-rank: top-5 (bge-v2) · retriever policy v3"},
            "metric": {"label": "context-overflow rate", "baseline": "6.1%", "gate": "≤ 2.0%", "projected": "0.3%"},
            "quality": "+2.1", "sessions": "1,200",
            "reasoning": "The fix is a capability the retriever was missing — a chunk cap + re-rank — not a prompt “try harder”. Rehearsed on real flagged traces before shipping.",
        },
        "traces": [
            {"id": "tr-1030", "agent": "Search Agent", "intent": "Policy lookup", "meta": "3.6s · Planner Drift"},
            {"id": "tr-1035", "agent": "Finance Extractor", "intent": "Invoice reconciliation", "meta": "6.1s · Tool Drift"},
        ],
    },
    {
        "id": "INC-990", "glyph": "finance", "agent": "RetireWell 401(k) Planner",
        "failure": "Individualized-advice guardrail breach", "pillars": ["Safety"],
        "stage": "remediate", "age": "35 mins ago", "status": "escalated",
        "dispo": "Awaiting human review", "dispo_class": "warn",
        "policy": "finance_guardrail_v1", "band": None, "confidence": 0.88,
        "action": "Prompt rewrite · Guardrail tweak",
        "timeline": [
            {"stage": "gate", "status": "done", "when": "35 mins ago", "note": "no_financial_advice judge fired on 2.4% of answers — the assistant named specific funds and a target allocation, breaching the 0.5% guardrail."},
            {"stage": "rca", "status": "done", "when": "28 mins ago", "note": "Multi-turn follow-ups inherit the user’s “just tell me what to buy” framing and slip past the educator-not-fiduciary guardrail on turn 3+."},
            {"stage": "simulate", "status": "done", "when": "15 mins ago", "note": "Replayed 950 flagged sessions with a hardened follow-up preamble + decline-and-redirect exemplar. Projected breach 0.1%, confidence 0.88."},
            {"stage": "remediate", "status": "queued", "when": "awaiting sign-off", "note": "finance_guardrail_v1 is `always open_ticket` — a regulated agent never auto-ships. Routed to #compliance for human approval."},
        ],
        "fix": {
            "change": {"before": "follow-up turns inherit user framing · no decline exemplar", "after": "hardened follow-up preamble · decline-and-redirect exemplar · fund-naming + allocation blocked"},
            "metric": {"label": "no_financial_advice breach", "baseline": "2.4%", "gate": "≤ 0.5%", "projected": "0.1%"},
            "quality": "±0", "sessions": "950",
            "reasoning": "Candidate is strong (0.88), but policy forces human sign-off for this regulated agent — a human audits the self-verification, they don’t re-derive the fix.",
        },
        "traces": [
            {"id": "tr-1041", "agent": "RetireWell 401(k)", "intent": "Rollover + allocation", "meta": "3.3s · Guardrail breach"},
        ],
    },
    {
        "id": "INC-993", "glyph": "prompt", "agent": "Support Agent",
        "failure": "Tone regression", "pillars": ["Transparency", "Fairness"],
        "stage": "simulate", "age": "25 mins ago", "status": "open",
        "dispo": "Rehearsing candidate", "dispo_class": "run",
        "policy": "client_assist_v3", "band": 0.85, "confidence": None,
        "action": "Prompt rewrite",
        "timeline": [
            {"stage": "gate", "status": "done", "when": "25 mins ago", "note": "Tone judge agreement dropped 11% after a prompt edit shipped in release v1.9.2."},
            {"stage": "rca", "status": "done", "when": "22 mins ago", "note": "A newly added “be concise” instruction stripped empathetic framing, disproportionately affecting refund and cancellation flows."},
            {"stage": "simulate", "status": "active", "when": "18 mins ago", "note": "A/B replaying 800 conversations against the prior template. Awaiting statistical significance before a confidence score is assigned."},
            {"stage": "remediate", "status": "queued", "when": "queued", "note": "Pending simulation sign-off. Candidate: restore an empathy preamble scoped to sensitive flows."},
        ],
        "fix": {
            "change": {"before": 'System: "Be concise."', "after": 'System: "Be concise, but keep an empathetic opening on refund & cancellation flows."'},
            "metric": {"label": "tone-judge agreement", "baseline": "−11%", "gate": "≥ baseline", "projected": "measuring…"},
            "quality": "tbd", "sessions": "800",
            "reasoning": "A/B replay in progress; no confidence score until the candidate reaches statistical significance against the prior template.",
        },
        "traces": [
            {"id": "tr-1036", "agent": "Support Agent", "intent": "Escalation routing", "meta": "4.4s · Planner Drift"},
        ],
    },
    {
        "id": "INC-994", "glyph": "tool", "agent": "Financial Doc Extractor",
        "failure": "Stuck in infinite loop", "pillars": ["Reliability", "Safety"],
        "stage": "rca", "age": "1 hour ago", "status": "open",
        "dispo": "Diagnosing · RCA", "dispo_class": "idle",
        "policy": "client_assist_v3", "band": 0.85, "confidence": None,
        "action": "Guardrail tweak · Circuit break",
        "timeline": [
            {"stage": "gate", "status": "done", "when": "1 hour ago", "note": "Trajectory monitor flagged 14 traces exceeding 20 tool calls with zero task progress."},
            {"stage": "rca", "status": "active", "when": "48 mins ago", "note": "Investigating a retry cycle between the search and calculator tools when a currency-conversion argument returns null."},
            {"stage": "simulate", "status": "queued", "when": "queued", "note": "Blocked on RCA. Proposed guard: cap tool-call depth at 8 and short-circuit null-argument retries."},
            {"stage": "remediate", "status": "queued", "when": "queued", "note": "Not started."},
        ],
        "fix": None,
        "traces": [
            {"id": "tr-1029", "agent": "Support Agent", "intent": "Refund processing", "meta": "4.2s · Tool Drift"},
            {"id": "tr-1032", "agent": "Support Agent", "intent": "Account cancellation", "meta": "5.1s · Tool Drift"},
        ],
    },
    {
        "id": "INC-995", "glyph": "parser", "agent": "Code Review Copilot",
        "failure": "JSON schema violation", "pillars": ["Reliability"],
        "stage": "gate", "age": "2 hours ago", "status": "open",
        "dispo": "Triaging · gate", "dispo_class": "idle",
        "policy": None, "band": None, "confidence": None, "action": "Fall-back",
        "timeline": [
            {"stage": "gate", "status": "active", "when": "2 hours ago", "note": "Schema-validation judge rejected 3.8% of outputs (missing required “confidence” field), above the 1% gate."},
            {"stage": "rca", "status": "queued", "when": "queued", "note": "Queued. Preliminary signal points to a model version bump changing default field ordering."},
            {"stage": "simulate", "status": "queued", "when": "queued", "note": "Not started."},
            {"stage": "remediate", "status": "queued", "when": "queued", "note": "Not started."},
        ],
        "fix": None,
        "traces": [
            {"id": "tr-1033", "agent": "Code Copilot", "intent": "PR review synthesis", "meta": "5.0s · Schema violation"},
        ],
    },
    {
        "id": "INC-988", "glyph": "chat", "agent": "Support Agent",
        "failure": "Refund-policy hallucination", "pillars": ["Reliability", "Safety"],
        "stage": "remediate", "age": "3 hours ago", "status": "resolved",
        "dispo": "Auto-resolved · verified", "dispo_class": "ok",
        "policy": "client_assist_v3", "band": 0.85, "confidence": 0.91,
        "action": "Prompt rewrite · KB update",
        "timeline": [
            {"stage": "gate", "status": "done", "when": "3 hours ago", "note": "Hallucination judge fired: 4.0% of refund answers cited a non-existent 30-day window, above the 1% guardrail."},
            {"stage": "rca", "status": "done", "when": "2h 58m ago", "note": "Attributed to a stale KB snippet plus a prompt that never required citing the policy source span."},
            {"stage": "simulate", "status": "done", "when": "2h 50m ago", "note": "Replayed 1,500 flagged sessions with a refreshed KB + cite-the-source instruction. Projected hallucination 0.2%, confidence 0.91."},
            {"stage": "remediate", "status": "done", "when": "2h 44m ago", "note": "0.91 ≥ 0.85 band → shipped in-band. Re-measured the guardrail: 0.2% over the next 1,500 live sessions. Incident auto-closed."},
        ],
        "fix": {
            "change": {"before": "KB: refund-policy v2 (stale) · prompt: no source-cite requirement", "after": "KB: refund-policy v4 · prompt: “cite the policy source span for any time window”"},
            "metric": {"label": "hallucination rate", "baseline": "4.0%", "gate": "≤ 1.0%", "projected": "0.2%"},
            "quality": "+1.4", "sessions": "1,500", "verified": "0.2% over 1,500 post-ship sessions",
            "reasoning": "Missing capability: nothing required the agent to ground time-window claims in a cited span. Fix added the capability + refreshed the source, then verified on live traffic.",
        },
        "traces": [
            {"id": "tr-1021", "agent": "Support Agent", "intent": "Refund window query", "meta": "2.9s · Hallucination"},
        ],
    },
]

# NOTE: the dashboard's quality rollup (per-app score + pillar aggregate) is no
# longer seeded here — it is *derived* from real verdict records by
# `eeof_core.rollups.quality_rollup` (verdicts by agent + by judge→pillar). The
# incident agent names above intentionally match the evaluated agents in
# `eeof_core.seed_demo.APP_PROFILES` so an incident ties back to a real breach.
