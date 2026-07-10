"""Dashboard rollups — Quality and Spend, aggregated from real records.

Nothing here is a display constant. Quality is computed by aggregating the
**verdict** rows produced by Evaluation (grouped by agent for Application quality,
by judge→pillar for Quality by pillar). Spend is computed from real counts — the
**token** totals on Observability batches, plus verdict / question / persona /
incident counts — priced with synthetic per-unit rates. Run the pipeline (or the
demo seed in `seed_demo.py`) and these numbers move because the underlying rows do.

Read-only; used by observability-svc (and re-exported to self-heal) so the whole
dashboard reads from one derivation.
"""

from __future__ import annotations

from .dataplane import get_table, keys
from .models import QUALITY_PILLARS, pillar_for

# Synthetic per-unit rates (USD). The *quantities* are real; only the price is
# fabricated — same posture as every other demo number.
RATE_PERSONA = 0.05
RATE_QUESTION = 0.03
RATE_SIM_PER_1K_TOKENS = 0.020
RATE_VERDICT = 0.120
RATE_BATCH = 0.50
RATE_INGEST_PER_1K_TOKENS = 0.004
RATE_INCIDENT = 0.40


async def _all_verdicts(tenant: str) -> list[dict]:
    """Every verdict row for the tenant, walking its verdict sets."""
    gsipk, _ = keys.verdictset_gsi(tenant, "")
    vsets = await get_table().query_gsi(gsipk)
    out: list[dict] = []
    for row in vsets:
        vs_id = row["data"]["id"]
        rows = await get_table().query(keys.verdict_pk(vs_id), "VERDICT#")
        out.extend(r["data"] for r in rows)
    return out


async def _run_agent_map(tenant: str) -> dict[str, str]:
    """run_id → agent name, from the run's frozen adapter snapshot.

    Groups by the adapter's human display name (config.display_name) rather than
    the raw registry name, so distinct adapter records for the *same* product
    (e.g. a baseline and a guardrail-regression variant of one agent) roll up
    into a single Application-quality row. Falls back to the registry name.
    """
    gsipk, _ = keys.run_gsi(tenant, "", "")
    rows = await get_table().query_gsi(gsipk)
    m: dict[str, str] = {}
    for r in rows:
        snap = r["data"].get("adapter_snapshot") or {}
        display = snap.get("display_name") or (snap.get("config") or {}).get("display_name")
        m[r["data"]["id"]] = display or snap.get("name", "Unknown agent")
    return m


def _pillar_of(v: dict) -> str:
    return v.get("pillar") or pillar_for(v.get("judge_ref", ""))


async def quality_rollup(tenant: str) -> dict:
    """Application quality (by agent) + Quality by pillar (by judge→pillar)."""
    verdicts = await _all_verdicts(tenant)
    if not verdicts:
        return {"applications": [], "pillars": [], "platform_mean": 0}

    agent_of = await _run_agent_map(tenant)

    # Application quality — mean verdict score per agent, 0..100.
    by_agent: dict[str, list[float]] = {}
    for v in verdicts:
        agent = agent_of.get(v["run_id"], "Unknown agent")
        by_agent.setdefault(agent, []).append(v["score"])
    apps = [
        {"name": name, "score": round(100 * sum(s) / len(s)), "evaluations": len(s)}
        for name, s in by_agent.items()
    ]
    apps.sort(key=lambda a: a["score"], reverse=True)

    # Quality by pillar — mean verdict score per pillar across all agents.
    by_pillar: dict[str, list[float]] = {}
    for v in verdicts:
        by_pillar.setdefault(_pillar_of(v), []).append(v["score"])
    pillar_scores = {
        name: round(100 * sum(s) / len(s))
        for name in QUALITY_PILLARS if (s := by_pillar.get(name))
    }
    # Delta = each pillar relative to the fleet's average pillar (a real
    # cross-sectional signal: which pillars lead or lag the platform average).
    fleet_avg = round(sum(pillar_scores.values()) / len(pillar_scores)) if pillar_scores else 0
    pillars = [
        {"name": name, "score": score, "delta": score - fleet_avg}
        for name, score in pillar_scores.items()
    ]

    platform_mean = round(sum(a["score"] for a in apps) / len(apps)) if apps else 0
    return {"applications": apps, "pillars": pillars, "platform_mean": platform_mean}


async def spend_rollup(tenant: str) -> dict:
    """Per-stage 24h spend, derived from real record counts + token totals."""
    table = get_table()

    # personas
    personas = await table.query(keys.persona_pk(tenant), "PERSONA#")
    n_personas = len(personas)

    # seed sets → questions
    ss_gsipk, _ = keys.seedset_gsi(tenant, "")
    seed_sets = await table.query_gsi(ss_gsipk)
    n_questions = sum(r["data"].get("question_count", 0) for r in seed_sets)

    # batches → tokens (simulation + observability ingest)
    batches = await table.query(f"TENANT#{tenant}#BATCH", "BATCH#")
    total_tokens = sum(r["data"].get("tokens", 0) for r in batches)
    n_batches = len(batches)

    # verdicts (evaluation)
    vs_gsipk, _ = keys.verdictset_gsi(tenant, "")
    vsets = await table.query_gsi(vs_gsipk)
    n_verdicts = sum(r["data"].get("verdict_count", 0) for r in vsets)

    # open self-heal incidents (may be absent until self-heal-svc seeds them)
    heal = await table.query(keys.heal_incident_pk(tenant), "HEAL_INCIDENT#")
    n_open_incidents = sum(1 for r in heal if r["data"].get("status") != "resolved")

    stages = [
        {"slug": "persona-lab", "label": "Persona Lab",
         "amount": round(n_personas * RATE_PERSONA, 2)},
        {"slug": "question-generation", "label": "Question Gen",
         "amount": round(n_questions * RATE_QUESTION, 2)},
        {"slug": "simulation", "label": "Simulation",
         "amount": round(total_tokens / 1000 * RATE_SIM_PER_1K_TOKENS, 2)},
        {"slug": "evaluation", "label": "Evaluation",
         "amount": round(n_verdicts * RATE_VERDICT, 2)},
        {"slug": "observability", "label": "Observability",
         "amount": round(n_batches * RATE_BATCH + total_tokens / 1000 * RATE_INGEST_PER_1K_TOKENS, 2)},
        {"slug": "self-heal", "label": "Self-Heal",
         "amount": round(n_open_incidents * RATE_INCIDENT, 2)},
    ]
    total = round(sum(s["amount"] for s in stages), 2)
    return {"stages": stages, "total": total}
