"""Realistic demo dataset — real pipeline records, written once per tenant.

The dashboard's quality / spend / self-heal numbers are *derived by aggregation*
from real records (see `rollups.py`), never from display constants. For that
aggregation to have something to chew on, a fresh `local` boot writes one
end-to-end lineage per demo agent straight into the data plane — the same row
shapes the qgen/sim/eval/observability workers produce, just seeded rather than
computed by a live LLM run (deterministic, offline, free).

Per agent it writes: a **seed set** → a **run** → a **verdict set** with one
**verdict per built-in judge** (scored along that judge's pillar) → a **batch**
with a real token count. Everything downstream — Application quality (verdicts by
agent), Quality by pillar (verdicts by judge→pillar), Spend by stage (tokens +
verdict/question counts), and Self-Heal incidents (pillar pass-rate breaches) —
then aggregates from these rows. Idempotent: it no-ops if verdict sets exist.

Synthetic scores, real derivation path.
"""

from __future__ import annotations

from .dataplane import get_table, keys
from .ids import new_id
from .messaging import config_hash
from .models import CORE_JUDGES, Batch, SeedSet, VerdictSet, iso
from .models.run import Run, RunState
from .models.verdict import Verdict

# Per-agent quality profile: a 0..1 score per pillar. These are the only
# synthetic inputs; every dashboard figure is aggregated back out of the verdict
# rows they generate. Deliberately varied so the six-pillar card and the per-app
# list read like a real fleet (a weakest pillar, a struggling agent, etc.).
APP_PROFILES: list[dict] = [
    {
        "name": "Support Agent", "questions": 48, "tokens": 128_400,
        "pillars": {"Safety": 0.93, "Privacy": 0.99, "Reliability": 0.95,
                    "Explainability": 0.93, "Transparency": 0.96, "Fairness": 0.95},
    },
    {
        "name": "Code Review Copilot", "questions": 40, "tokens": 96_200,
        "pillars": {"Safety": 0.95, "Privacy": 0.97, "Reliability": 0.93,
                    "Explainability": 0.90, "Transparency": 0.92, "Fairness": 0.90},
    },
    {
        "name": "Internal Knowledge Search", "questions": 36, "tokens": 152_700,
        "pillars": {"Safety": 0.88, "Privacy": 0.95, "Reliability": 0.80,
                    "Explainability": 0.82, "Transparency": 0.84, "Fairness": 0.90},
    },
    {
        "name": "RetireWell 401(k) Planner", "questions": 44, "tokens": 141_300,
        "pillars": {"Safety": 0.78, "Privacy": 0.96, "Reliability": 0.90,
                    "Explainability": 0.85, "Transparency": 0.82, "Fairness": 0.93},
    },
    {
        "name": "Financial Doc Extractor", "questions": 32, "tokens": 173_900,
        "pillars": {"Safety": 0.84, "Privacy": 0.93, "Reliability": 0.72,
                    "Explainability": 0.78, "Transparency": 0.80, "Fairness": 0.88},
    },
]


def _jitter(score: float, salt: str) -> float:
    """Small deterministic per-judge wobble so scores aren't flat within a pillar."""
    h = sum(ord(c) for c in salt) % 7  # 0..6
    return max(0.0, min(1.0, round(score + (h - 3) * 0.008, 4)))


async def has_demo_data(tenant: str) -> bool:
    gsipk, _ = keys.verdictset_gsi(tenant, "")
    rows = await get_table().query_gsi(gsipk)
    return bool(rows)


async def ensure_demo_data(tenant: str, workspace: str = "trust-and-safety") -> dict:
    """Write one end-to-end lineage per demo agent. Idempotent."""
    if await has_demo_data(tenant):
        return {"seeded": False, "reason": "verdict sets already present"}

    table = get_table()
    ts = iso()
    made = {"runs": 0, "verdict_sets": 0, "verdicts": 0, "seed_sets": 0, "batches": 0}

    for app in APP_PROFILES:
        run_id = new_id("run")
        seed_set_id = new_id("seed_set")
        vs_id = new_id("verdict_set")

        # --- seed set (question-generation output) ---
        seed = SeedSet(
            id=seed_set_id, tenant=tenant, workspace=workspace, strategy="rainbow",
            persona_refs=[], question_count=app["questions"],
        )
        gsipk, gsisk = keys.seedset_gsi(tenant, seed.created_at)
        await table.put({
            "PK": keys.seedset_pk(tenant), "SK": keys.seedset_sk(seed_set_id),
            "GSIPK": gsipk, "GSISK": gsisk, "type": "seed_set",
            "data": seed.model_dump(mode="json"),
        })
        made["seed_sets"] += 1

        # --- run (simulation output) ---
        run = Run(
            id=run_id, tenant=tenant, workspace=workspace, seed_set_id=seed_set_id,
            seed_set_question_count=app["questions"],
            adapter_snapshot={"id": f"adp_{app['name']}", "name": app["name"]},
            config_hash=config_hash({"agent": app["name"], "seed": seed_set_id}),
            state=RunState.ready, total_questions=app["questions"], completed=app["questions"],
            output={"tokens": app["tokens"]},
        )
        gsipk, gsisk = keys.run_gsi(tenant, run.state.value, run.created_at)
        await table.put({
            "PK": keys.run_pk(tenant), "SK": keys.run_sk(run_id),
            "GSIPK": gsipk, "GSISK": gsisk, "type": "run",
            "data": run.model_dump(mode="json"),
        })
        made["runs"] += 1

        # --- verdicts: one per built-in judge, scored along its pillar ---
        verdicts: list[Verdict] = []
        for j in CORE_JUDGES:
            pillar = j.get("pillar", "Reliability")
            base = app["pillars"].get(pillar, 0.85)
            score = _jitter(base, j["name"] + app["name"])
            passed = score >= j.get("threshold", 0.7)
            v = Verdict(
                id=new_id("verdict"), verdict_set_id=vs_id, run_id=run_id,
                trace_id=f"trc_{run_id[-6:]}_{j['name']}", question_id=f"q_{j['name']}",
                judge_ref=f"{j['name']}@v1", passed=passed, score=score,
                dimension=j.get("dimension", j["name"]), verdict="pass" if passed else "fail",
                pillar=pillar,  # denormalised for fast rollups
            )
            verdicts.append(v)
            gsipk, gsisk = keys.verdict_gsi(run_id, v.id)
            await table.put({
                "PK": keys.verdict_pk(vs_id), "SK": keys.verdict_sk(v.id),
                "GSIPK": gsipk, "GSISK": gsisk, "type": "verdict",
                "data": v.model_dump(mode="json"),
            })
        made["verdicts"] += len(verdicts)

        # --- verdict set (evaluation output) ---
        pass_count = sum(1 for v in verdicts if v.passed)
        vset = VerdictSet(
            id=vs_id, tenant=tenant, workspace=workspace, run_ids=[run_id],
            judge_refs=[f"{j['name']}@v1" for j in CORE_JUDGES],
            verdict_count=len(verdicts), pass_count=pass_count,
            pass_rate=round(pass_count / len(verdicts), 4) if verdicts else 0.0,
            aggregate_scores={v.dimension: v.score for v in verdicts},
        )
        gsipk, gsisk = keys.verdictset_gsi(tenant, vset.created_at)
        await table.put({
            "PK": keys.verdictset_pk(tenant), "SK": keys.verdictset_sk(vs_id),
            "GSIPK": gsipk, "GSISK": gsisk, "type": "verdict_set",
            "data": vset.model_dump(mode="json"),
        })
        made["verdict_sets"] += 1

        # --- batch (observability ingest aggregate, carries real token count) ---
        batch = Batch(
            run_id=run_id, tenant=tenant, traces=app["questions"], tokens=app["tokens"],
            first_seen=ts, last_seen=ts,
        )
        await table.put({
            "PK": f"TENANT#{tenant}#BATCH", "SK": f"BATCH#{run_id}",
            "type": "batch", "data": batch.model_dump(mode="json"),
        })
        made["batches"] += 1

    return {"seeded": True, **made}
