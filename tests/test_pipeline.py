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


@pytest.mark.asyncio
async def test_builtin_judge_catalogue_is_sync_and_complete():
    """The sync judge registry seeds the full research-grounded core catalogue,
    each judge carrying its card metadata; re-seeding is idempotent."""
    from eeof_core.models import CORE_JUDGES
    from evaluation_svc.judges import ensure_builtin_judges, list_judges

    await ensure_builtin_judges(TENANT)
    await ensure_builtin_judges(TENANT)  # idempotent — no duplicates

    judges = {j.name: j for j in await list_judges(TENANT)}
    assert set(judges) == {spec["name"] for spec in CORE_JUDGES}

    faith = judges["faithfulness"]
    assert faith.kind == "builtin"
    assert faith.dimension == "faithfulness"
    assert faith.family == "frontier-LLM"
    assert faith.reference == "retrieval-context"
    assert faith.threshold == 0.75
    assert faith.ref == "faithfulness@v1"
    # Non-LLM judges are a first-class catalogue category (AlignScore / Detoxify).
    assert judges["factual_consistency"].family == "non-LLM"
    assert judges["hallucination"].family == "specialist-LLM"


@pytest.mark.asyncio
async def test_finance_guardrail_judges_are_catalogued():
    """The finance-domain guardrail judges ship in the built-in catalogue."""
    from eeof_core.models import CORE_JUDGES
    from evaluation_svc.judges import ensure_builtin_judges, list_judges

    await ensure_builtin_judges(TENANT)
    judges = {j.name: j for j in await list_judges(TENANT)}

    for name in ("no_financial_advice", "regulatory_disclosure", "numeric_accuracy"):
        assert name in {spec["name"] for spec in CORE_JUDGES}
        assert name in judges
    # The numeric verifier is deterministic / non-LLM; the advice guardrail is a
    # high-bar frontier judge.
    assert judges["numeric_accuracy"].family == "non-LLM"
    assert judges["no_financial_advice"].threshold >= 0.85
    assert judges["no_financial_advice"].family == "frontier-LLM"


@pytest.mark.asyncio
async def test_core_persona_library_seeded_and_diverse():
    """The core persona library seeds idempotently and covers the intended mix:
    diverse agent-testing profiles + financial personas, and no multilingual ones."""
    from eeof_core.models import CORE_PERSONAS
    from persona_svc.app import ensure_builtin_personas

    await ensure_builtin_personas(TENANT)
    await ensure_builtin_personas(TENANT)  # idempotent — no dup versions

    rows = await get_table().query(keys.persona_pk(TENANT), "PERSONA#")
    seeded = {r["data"]["name"] for r in rows}
    assert {spec["name"] for spec in CORE_PERSONAS} <= seeded

    finance = [p for p in CORE_PERSONAS if "finance" in p.get("tags", [])]
    assert len(finance) >= 3  # at least three financial-domain personas
    assert any("adversarial" in p.get("tags", []) for p in CORE_PERSONAS)
    # No multilingual/locale coverage was added.
    assert not any("multilingual" in p.get("tags", []) for p in CORE_PERSONAS)
    assert all(not p.get("locale") for p in CORE_PERSONAS)


@pytest.mark.asyncio
async def test_builtin_401k_agent_onboarded_as_rest_adapter():
    """The 401(k) agent is catalogued and onboarded as a REST adapter pointing at
    the agent-under-test endpoint — idempotently."""
    from eeof_core.config import settings
    from eeof_core.models import get_agent
    from simulation_svc.adapters import ensure_builtin_adapters, list_adapters

    agent = get_agent("retirement-401k")
    assert agent and agent["transport"] == "rest"

    await ensure_builtin_adapters(TENANT)
    await ensure_builtin_adapters(TENANT)  # idempotent

    adapters = {a.name: a for a in await list_adapters(TENANT)}
    assert "retirement-401k" in adapters
    rest = adapters["retirement-401k"]
    assert rest.transport == "rest"
    assert rest.config["endpoint"] == settings.agent_under_test_url
    assert len([a for a in await list_adapters(TENANT) if a.name == "retirement-401k"]) == 1


@pytest.mark.asyncio
async def test_multiturn_followup_is_grounded_in_history():
    """Each follow-up user turn is generated from the full running transcript, so
    turn n sees turns 1..n-1 — not just the opener."""
    from eeof_core.models import PersonaRef, Question
    from simulation_svc.sim import simulate_conversation

    calls: list[tuple[str, int]] = []

    class RecordingProvider:
        name = "recording"

        async def chat(self, *, system, messages, max_tokens=1024, temperature=0.7):
            calls.append((system, len(messages)))
            # Alternate plausible text so turns aren't empty.
            return "agent reply" if "agent under test" in system else "and what about X?"

    q = Question(
        id="q1", seed_set_id="ss1", prompt="How does the employer match work?",
        persona=PersonaRef(id="persona_femi", version="1.0.0", name="First-Timer Femi",
                           tone="casual", tech_savviness="novice"),
        rubric="numeric_accuracy",
    )
    # A "turn" is one user↔agent exchange, so max_turns=3 yields three exchanges
    # (six messages), alternating user then agent.
    turns = await simulate_conversation(q, {}, RecordingProvider(), max_turns=3)

    # user, agent, user, agent, user, agent
    assert [t.role for t in turns] == ["user", "agent", "user", "agent", "user", "agent"]

    # The user-simulator calls (not the agent calls) must see a growing history.
    sim_calls = [n for (system, n) in calls if "role-playing" in system]
    assert sim_calls, "the user simulator was never invoked for a follow-up"
    assert all(n > 1 for n in sim_calls)  # more than just the opening prompt
    assert sim_calls == sorted(sim_calls)  # history grows across turns
