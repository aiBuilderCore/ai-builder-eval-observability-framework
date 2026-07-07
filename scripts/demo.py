"""End-to-end pipeline demo against a running edge (run_all must be up).

Drives the four-tuple lineage persona -> question -> run -> verdict -> evidence
purely through the public API, polling the uniform jobs endpoint for async work.

    uv run python scripts/run_all.py        # terminal 1
    uv run python scripts/demo.py           # terminal 2
"""

from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8080/api/v1"
HEADERS = {"Authorization": "Bearer dev"}


def poll(client: httpx.Client, job_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
        if job["state"] in ("ready", "shipped", "failed"):
            return job
        time.sleep(0.4)
    raise TimeoutError(f"job {job_id} did not finish")


def main() -> None:
    with httpx.Client(timeout=30) as c:
        # 1. Persona (sync)
        persona = c.post(
            f"{BASE}/personas",
            headers=HEADERS,
            json={
                "name": "Onboarding Olivia",
                "role": "First-time user, mid-market ops lead",
                "tone": "casual",
                "tech_savviness": "novice",
                "goals": ["Produce a first useful artifact in under 10 minutes."],
                "edge_cases": ["Asks vague open-ended questions.", "Skips long responses."],
                "primary_rubric": "helpfulness",
            },
        ).json()
        print("persona:", persona["id"], persona["version"])

        # 2. Adapter (sync) — local demo target (provider stands in as the agent)
        adapter = c.post(
            f"{BASE}/adapters",
            headers=HEADERS,
            json={"name": "demo-agent", "transport": "rest", "config": {}},
        ).json()
        print("adapter:", adapter["id"], "v", adapter["version"])

        # 3. Question generation (async)
        qs = c.post(
            f"{BASE}/question-sets",
            headers=HEADERS,
            json={
                "persona_refs": [{"id": persona["id"], "version": persona["version"]}],
                "count_per_persona": 4,
            },
        ).json()
        job = poll(c, qs["job_id"])
        seed_set_id = job["result"]["seed_set_id"]
        print("seed set:", seed_set_id, "questions:", job["result"]["question_count"])

        # 4. Simulation (async)
        run = c.post(
            f"{BASE}/simulation/runs",
            headers=HEADERS,
            json={"seed_set_id": seed_set_id, "adapter_id": adapter["id"], "max_turns": 4},
        ).json()
        run_id = run["run_id"]
        poll(c, run["job_id"])
        print("run:", run_id)

        # 5. Evaluation (async)
        ev = c.post(
            f"{BASE}/evaluation/jobs", headers=HEADERS, json={"run_ids": [run_id]}
        ).json()
        ejob = poll(c, ev["job_id"])
        vs_id = ejob["result"]["verdict_set_id"]
        print("verdict set:", vs_id, "pass_rate:", ejob["result"]["pass_rate"])

        # 6. Deploy gate + evidence (async)
        gate = c.get(f"{BASE}/observability/gate/{vs_id}", headers=HEADERS).json()
        print("gate:", gate["decision"], gate["pass_rate"])
        pack = c.post(
            f"{BASE}/observability/evidence",
            headers=HEADERS,
            json={"candidate": run_id, "verdict_set_ids": [vs_id]},
        ).json()
        pjob = poll(c, pack["job_id"])
        print("evidence pack:", pjob["result"]["pack_id"], "decision:", pjob["result"]["decision"])
        print("\n✓ end-to-end lineage complete")


if __name__ == "__main__":
    main()
