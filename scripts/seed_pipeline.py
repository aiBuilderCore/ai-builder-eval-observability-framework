"""Populate the interactive surfaces by driving the REAL pipeline over the API.

`ensure_demo_data` (the SEED_DEMO path in run_all) seeds the dashboard /
observability rollups directly into the data plane, but it does not create the
job-backed records the Question-Generation, Evaluation and Self-Heal *lists* read
(`GET /jobs`, real breach incidents). This script fills that gap by driving the
genuine public pipeline once, so every surface has data that came out of a real
worker — no hand-written job envelopes.

It registers the 401(k) agent (+ a guardrail-regression variant), reuses the
core-library personas, and runs two lineages through the edge:

  • healthy  : persona → qgen → simulation → evaluation → deploy gate → evidence
  • breach   : adversarial persona → qgen → sim (advice_leak) → evaluation
               → the eval worker's detector opens a real Self-Heal incident

Idempotent: it no-ops if a question-generation job already exists (so re-running
`bootstrap.sh` against a persistent infra backend does not double-seed; a fresh
in-memory `local` plane always seeds).

    uv run python scripts/seed_pipeline.py        # edge must be up
"""

from __future__ import annotations

import sys
import time

import httpx

BASE = "http://127.0.0.1:8080/api/v1"
HEADERS = {"Authorization": "Bearer dev"}
AGENT_ENDPOINT = "http://127.0.0.1:8097/chat"

HEALTHY_JUDGES = ["helpfulness@v1", "answer_relevance@v1"]
FINANCE_JUDGES = ["no_financial_advice@v1", "regulatory_disclosure@v1", "numeric_accuracy@v1"]


def poll(c: httpx.Client, job_id: str, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = c.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
        if job["state"] in ("ready", "shipped", "failed"):
            return job
        time.sleep(0.4)
    raise TimeoutError(f"job {job_id} did not finish")


def pick_persona(personas: list[dict], rubric: str, fallback_idx: int = 0) -> dict:
    return next((p for p in personas if p.get("primary_rubric") == rubric),
                personas[fallback_idx])


def ensure_adapter(c: httpx.Client, adapters: list[dict], name: str, config: dict) -> dict:
    existing = next((a for a in adapters if a.get("name") == name), None)
    if existing:
        return existing
    return c.post(
        f"{BASE}/adapters", headers=HEADERS,
        json={"name": name, "transport": "rest", "config": config},
    ).json()


def lineage(c: httpx.Client, persona: dict, adapter: dict, judges: list[str],
            *, evidence: bool, label: str) -> None:
    """Run one persona × adapter lineage end-to-end through the public API."""
    # Small counts on purpose: this is a demo seed, not a load test. Fewer
    # questions × shorter conversations = far fewer LLM calls, so the lineage
    # finishes quickly even when the free-tier provider is rate-limiting.
    qs = c.post(
        f"{BASE}/question-sets", headers=HEADERS,
        json={"persona_refs": [{"id": persona["id"], "version": persona["version"]}],
              "count_per_persona": 2},
    ).json()
    seed_set_id = poll(c, qs["job_id"])["result"]["seed_set_id"]

    run = c.post(
        f"{BASE}/simulation/runs", headers=HEADERS,
        json={"seed_set_id": seed_set_id, "adapter_id": adapter["id"], "max_turns": 2},
    ).json()
    run_id = run["run_id"]
    poll(c, run["job_id"])

    ev = c.post(
        f"{BASE}/evaluation/jobs", headers=HEADERS,
        json={"run_ids": [run_id], "judge_refs": judges},
    ).json()
    ejob = poll(c, ev["job_id"])
    vs_id = ejob["result"]["verdict_set_id"]
    pass_rate = ejob["result"]["pass_rate"]
    print(f"  {label}: run {run_id} · verdict set {vs_id} · pass_rate {pass_rate}")

    if evidence:
        gate = c.get(f"{BASE}/observability/gate/{vs_id}", headers=HEADERS).json()
        pack = c.post(
            f"{BASE}/observability/evidence", headers=HEADERS,
            json={"candidate": run_id, "verdict_set_ids": [vs_id]},
        ).json()
        pjob = poll(c, pack["job_id"])
        print(f"           gate {gate['decision']} · evidence {pjob['result']['pack_id']}")


def main() -> int:
    with httpx.Client(timeout=30) as c:
        # Idempotency: a qgen job already present ⇒ this backend is seeded.
        try:
            jobs = c.get(f"{BASE}/jobs", headers=HEADERS).json()
        except httpx.HTTPError as e:
            print(f"seed_pipeline: edge not reachable ({e}); skipping", file=sys.stderr)
            return 0
        if any(j.get("stage") == "qgen" for j in jobs):
            print("seed_pipeline: pipeline data already present — nothing to do")
            return 0

        personas = c.get(f"{BASE}/personas", headers=HEADERS).json()
        if not personas:
            print("seed_pipeline: no personas from the core library yet; skipping", file=sys.stderr)
            return 0
        healthy_persona = pick_persona(personas, "numeric_accuracy")
        breach_persona = pick_persona(personas, "no_financial_advice", fallback_idx=-1)

        adapters = c.get(f"{BASE}/adapters", headers=HEADERS).json()
        healthy_adapter = ensure_adapter(
            c, adapters, "retirement-401k",
            {"endpoint": AGENT_ENDPOINT, "agent": "retirement-401k",
             "display_name": "RetireWell 401(k) Planner",
             "domain": "financial-services / retirement"},
        )
        regression_adapter = ensure_adapter(
            c, adapters, "RetireWell (guardrail-regression)",
            {"endpoint": AGENT_ENDPOINT, "agent": "retirement-401k",
             "display_name": "RetireWell 401(k) Planner",
             "domain": "financial-services / retirement", "scenario": "advice_leak"},
        )

        print("seed_pipeline: driving the real pipeline (this exercises the workers)…")
        lineage(c, healthy_persona, healthy_adapter, HEALTHY_JUDGES,
                evidence=True, label="healthy")
        lineage(c, breach_persona, regression_adapter, FINANCE_JUDGES,
                evidence=False, label="breach")

        incs = c.get(f"{BASE}/self-heal/incidents", headers=HEADERS).json()
        print(f"seed_pipeline: done — {len(incs)} self-heal incident(s) opened from real breaches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
