"""In-process pipeline test — exercises every worker's domain logic on the
in-memory data plane, no HTTP, fully deterministic (echo provider).

persona snapshot -> qgen -> simulation -> evaluation -> evidence.
"""

from __future__ import annotations

import pytest

from eeof_core.dataplane import get_table, keys
from eeof_core.ids import new_id
from eeof_core.messaging import config_hash
from eeof_core.models import Job, JobState

from evaluation_svc.worker import EvalWorker
from observability_svc.worker import EvidenceWorker
from qgen_svc.worker import QGenWorker
from simulation_svc.worker import SimWorker

TENANT = "acme"
WS = "trust-and-safety"


def _job(kind: str, stage: str, inputs: dict) -> Job:
    return Job(
        job_id=new_id("job"), tenant=TENANT, workspace=WS, kind=kind, stage=stage,
        inputs=inputs, config_hash=config_hash(inputs),
    )


@pytest.mark.asyncio
async def test_full_pipeline():
    persona = {
        "id": "persona_olivia", "version": "1.0.0", "name": "Onboarding Olivia",
        "role": "ops lead", "tone": "casual", "tech_savviness": "novice",
        "goals": ["ship fast"], "edge_cases": ["asks vague questions"],
        "primary_rubric": "helpfulness",
    }

    # 1. Question generation
    qgen_job = _job("qgen.generate", "qgen", {
        "persona_snapshots": [persona], "count_per_persona": 3,
        "shapes": ["ambiguate", "adversify"], "scenarios": ["short.chat.easy"],
    })
    result = await QGenWorker().handle(qgen_job)
    seed_set_id = result["seed_set_id"]
    assert result["question_count"] == 3
    questions = await get_table().query(keys.question_pk(seed_set_id), "QUESTION#")
    assert len(questions) == 3

    # 2. Simulation
    sim_job = _job("simulation.run", "sim", {
        "run_id": new_id("run"), "seed_set_id": seed_set_id,
        "adapter_snapshot": {"transport": "rest", "config": {}}, "max_turns": 4, "concurrency": 4,
    })
    run_id = sim_job.inputs["run_id"]
    sim_result = await SimWorker().handle(sim_job)
    assert sim_result["traces"] == 3
    traces = await get_table().query(keys.trace_pk(run_id), "TRACE#")
    assert len(traces) == 3

    # 3. Evaluation
    eval_job = _job("evaluation.score", "eval", {
        "run_ids": [run_id], "judge_refs": ["helpfulness@v1"],
        "judge_rubrics": {"helpfulness@v1": "helpfulness"}, "aggregation": "majority",
    })
    eval_result = await EvalWorker().handle(eval_job)
    vs_id = eval_result["verdict_set_id"]
    assert eval_result["verdicts"] == 3
    assert 0.0 <= eval_result["pass_rate"] <= 1.0
    # verdicts are queryable by run via the GSI
    by_run = await get_table().query_gsi(f"RUN#{run_id}", "VERDICT#")
    assert len(by_run) == 3

    # 4. Evidence pack + deploy gate
    obs_job = _job("observability.evidence", "obs", {
        "candidate": run_id, "verdict_set_ids": [vs_id], "title": "test pack",
    })
    pack = await EvidenceWorker().handle(obs_job)
    assert pack["pack_id"].startswith("ev_")
    assert pack["decision"] in ("pass", "fail")


@pytest.mark.asyncio
async def test_worker_lifecycle_marks_ready():
    job = _job("qgen.generate", "qgen", {"persona_snapshots": [], "count_per_persona": 1})
    # Empty persona set still ships an (empty) seed set and marks ready.
    w = QGenWorker()
    await w._on_message(job.model_dump(mode="json"))
    from eeof_core.jobs import get_job
    stored = await get_job(TENANT, job.job_id)
    assert stored is not None
    assert stored.state == JobState.ready
