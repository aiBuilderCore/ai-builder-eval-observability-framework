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

# Seed sizing — one question-generation job over ALL personas, then both adapters
# simulate the same seed set and every run is scored by the ENTIRE judge catalogue
# (see `all_judge_refs`). Kept to 20 questions so the free-tier provider (which
# falls back to the offline echo judge under rate limits) still finishes in
# bootstrap while giving observability + self-heal a real cohort to work with.
SEED_QUESTION_TOTAL = 20
SIM_MAX_TURNS = 5
SIM_CONCURRENCY = 10


def poll(c: httpx.Client, job_id: str, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = c.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
        if job["state"] in ("ready", "shipped", "failed"):
            return job
        time.sleep(0.4)
    raise TimeoutError(f"job {job_id} did not finish")


def all_judge_refs(c: httpx.Client) -> list[str]:
    """Every judge in the catalogue, as `name@vN` refs — so each run is scored by
    the full panel rather than a hand-picked subset."""
    judges = c.get(f"{BASE}/judges", headers=HEADERS).json()
    return [f"{j['name']}@v{j['version']}" for j in judges]


def ensure_adapter(c: httpx.Client, adapters: list[dict], name: str, config: dict) -> dict:
    existing = next((a for a in adapters if a.get("name") == name), None)
    if existing:
        return existing
    return c.post(
        f"{BASE}/adapters", headers=HEADERS,
        json={"name": name, "transport": "rest", "config": config},
    ).json()


def generate_seed_set(c: httpx.Client, personas: list[dict], *, target_total: int) -> str:
    """Run ONE question-generation job over *all* personas, producing exactly
    `target_total` questions spread evenly across the persona × shape × scenario
    grid. Returns the frozen seed_set_id both adapters then simulate against."""
    persona_refs = [{"id": p["id"], "version": p["version"]} for p in personas]
    qs = c.post(
        f"{BASE}/question-sets", headers=HEADERS,
        json={"persona_refs": persona_refs, "target_total": target_total},
    ).json()
    result = poll(c, qs["job_id"])["result"]
    seed_set_id = result["seed_set_id"]
    print(
        f"seed_pipeline: qgen · {len(persona_refs)} personas · "
        f"{result.get('question_count', target_total)} questions · seed set {seed_set_id}"
    )
    return seed_set_id


def lineage(c: httpx.Client, seed_set_id: str, adapter: dict, judges: list[str],
            *, evidence: bool, label: str) -> None:
    """Simulate + evaluate one adapter against the shared seed set, end-to-end
    through the public API. Question generation is done once up front (all
    personas), so the whole seed is exactly SEED_QUESTION_TOTAL questions and both
    adapters run the same set — giving observability + self-heal a real cohort of
    conversations to work with."""
    run = c.post(
        f"{BASE}/simulation/runs", headers=HEADERS,
        json={"seed_set_id": seed_set_id, "adapter_id": adapter["id"],
              "max_turns": SIM_MAX_TURNS, "concurrency": SIM_CONCURRENCY},
    ).json()
    run_id = run["run_id"]
    poll(c, run["job_id"], timeout=600)

    ev = c.post(
        f"{BASE}/evaluation/jobs", headers=HEADERS,
        json={"run_ids": [run_id], "judge_refs": judges},
    ).json()
    ejob = poll(c, ev["job_id"], timeout=600)
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

        judges = all_judge_refs(c)
        print(f"seed_pipeline: driving the real pipeline · {len(judges)} judges in catalogue")
        # One question-generation job over ALL personas → exactly 20 questions.
        seed_set_id = generate_seed_set(c, personas, target_total=SEED_QUESTION_TOTAL)
        # Both adapters simulate the SAME seed set and every run is scored by the
        # ENTIRE judge catalogue, so observability has two full cohorts and the
        # guardrail judges open a real Self-Heal incident on the regression variant.
        lineage(c, seed_set_id, healthy_adapter, judges,
                evidence=True, label="healthy")
        lineage(c, seed_set_id, regression_adapter, judges,
                evidence=False, label="breach")

        incs = c.get(f"{BASE}/self-heal/incidents", headers=HEADERS).json()
        print(f"seed_pipeline: done — {len(incs)} self-heal incident(s) opened from real breaches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
