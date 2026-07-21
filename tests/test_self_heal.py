"""Self-Heal service tests — seed + read + the remediation-ship worker, driven
directly on the in-memory data plane (no HTTP), deterministic.
"""

from __future__ import annotations

import pytest

from eeof_core.ids import new_id
from eeof_core.messaging import config_hash
from eeof_core.models import Job

from self_heal_svc.store import (
    ensure_seeded,
    get_incident,
    get_quality,
    list_incidents,
    list_policies,
    summary,
)
from self_heal_svc.worker import RemediationWorker

# Isolated tenant: the evaluation worker's breach detector opens real incidents
# on whatever tenant a run is evaluated under (test_pipeline uses "acme"), so the
# exact seed-count assertions below run on their own tenant to stay deterministic.
TENANT = "acme-heal"
WS = "trust-and-safety"


def _job(inputs: dict) -> Job:
    return Job(
        job_id=new_id("job"), tenant=TENANT, workspace=WS,
        kind="self_heal.remediate", stage="heal",
        inputs=inputs, config_hash=config_hash(inputs),
    )


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_populated():
    await ensure_seeded(TENANT)
    await ensure_seeded(TENANT)  # second call must not duplicate
    incs = await list_incidents(TENANT)
    assert len(incs) == 6
    assert len(await list_policies(TENANT)) == 4


@pytest.mark.asyncio
async def test_summary_counts_open_incidents():
    s = await summary(TENANT)
    # 6 seeded, one resolved (INC-988) => 5 open.
    assert s.open_incidents == 5
    assert s.active_policies == 4


@pytest.mark.asyncio
async def test_quality_rollup_derives_from_verdicts():
    # Fresh tenant so pipeline-test verdicts don't leak in; seed a real lineage
    # then confirm quality is aggregated from those verdict rows (5 agents, 6 pillars).
    from eeof_core.seed_demo import APP_PROFILES, ensure_demo_data

    tenant = "acme-quality"
    await ensure_demo_data(tenant)
    q = await get_quality(tenant)
    apps = q["applications"]
    assert len(apps) == len(APP_PROFILES)          # one app per evaluated agent
    assert {a["name"] for a in apps} == {p["name"] for p in APP_PROFILES}
    assert len(q["pillars"]) == 6                   # all six pillars have verdicts
    assert all(a["evaluations"] > 0 for a in apps)  # scores came from real verdicts
    assert q["platform_mean"] == round(sum(a["score"] for a in apps) / len(apps))


@pytest.mark.asyncio
async def test_remediation_worker_closes_the_loop():
    await ensure_seeded(TENANT)
    result = await RemediationWorker().handle(_job({"incident_id": "INC-990", "action": "approve"}))
    assert result["status"] == "resolved" and result["shipped"] is True
    inc = await get_incident(TENANT, "INC-990")
    assert inc.status == "resolved"
    assert inc.fix is not None and inc.fix.verified is not None
    # The remediate timeline step is now done.
    assert [s for s in inc.timeline if s.stage == "remediate"][0].status == "done"


def _verdict(vs_id: str, dim: str, passed: bool, score: float, i: int):
    from eeof_core.models import Verdict

    return Verdict(
        id=new_id("verdict"), verdict_set_id=vs_id, run_id="sim_run1",
        trace_id=f"trc_{dim}_{i}", question_id=f"q{i}", judge_ref=f"{dim}@v1",
        passed=passed, score=score, dimension=dim, verdict="pass" if passed else "fail",
        rationale=f"named a specific fund on turn {i}", persona_name="Anxious-Investor Amir",
    )


@pytest.mark.asyncio
async def test_breach_opens_a_real_incident_detect_only():
    """A judge that fails its guardrail on real verdicts opens a detect-only
    self-heal incident — derived from the verdicts, no fabricated fix."""
    from eeof_core.dataplane import get_table, keys
    from eeof_core.models import VerdictSet
    from eeof_core.self_heal_detect import detect_incidents

    tenant = "acme-breach"
    vs = VerdictSet(
        id=new_id("verdict_set"), tenant=tenant, workspace=WS,
        run_ids=["sim_run1"], judge_refs=["no_financial_advice@v1", "helpfulness@v1"],
    )
    # no_financial_advice (threshold 0.9 → budget 0.10): all fail → breach.
    # helpfulness (threshold 0.7 → budget 0.30): all pass → no incident.
    verdicts = (
        [_verdict(vs.id, "no_financial_advice", False, 0.40, i) for i in range(3)]
        + [_verdict(vs.id, "helpfulness", True, 0.95, i) for i in range(3)]
    )

    opened = await detect_incidents(tenant, vs, verdicts, "RetireWell (guardrail-regression)")
    assert len(opened) == 1

    rows = await get_table().query(keys.heal_incident_pk(tenant), "HEAL_INCIDENT#")
    assert len(rows) == 1
    inc = rows[0]["data"]
    assert inc["agent"] == "RetireWell (guardrail-regression)"
    assert inc["failure"] == "no_financial_advice guardrail breach"
    assert inc["pillars"] == ["Safety"]
    assert inc["status"] == "open" and inc["stage"] == "rca"
    assert inc["fix"] is None and inc["confidence"] is None  # honest detect-only
    assert inc["incident_from"] == vs.id
    assert len(inc["traces"]) == 3                            # the real flagged traces
    assert all(t["agent"] == "RetireWell (guardrail-regression)" for t in inc["traces"])

    # Idempotent: re-detecting the same verdict set opens nothing new.
    again = await detect_incidents(tenant, vs, verdicts, "RetireWell (guardrail-regression)")
    assert again == []
    rows2 = await get_table().query(keys.heal_incident_pk(tenant), "HEAL_INCIDENT#")
    assert len(rows2) == 1


@pytest.mark.asyncio
async def test_policy_matches_by_structured_scope_and_captures_baseline():
    """With policies seeded, a breach is matched to the governing policy by its
    structured dimensions + agent scope, and a real passing trace is captured as
    the RCA baseline (mixed pass/fail group)."""
    from eeof_core.models import VerdictSet
    from eeof_core.self_heal_detect import detect_incidents

    tenant = "acme-policy"
    await ensure_seeded(tenant)  # loads the 4 built-in policies
    vs = VerdictSet(
        id=new_id("verdict_set"), tenant=tenant, workspace=WS,
        run_ids=["sim_run1"], judge_refs=["no_financial_advice@v1"],
    )
    # 3 fail + 2 pass (0.60 budget < 0.10 → breach); the passes seed the baseline.
    verdicts = (
        [_verdict(vs.id, "no_financial_advice", False, 0.40, i) for i in range(3)]
        + [_verdict(vs.id, "no_financial_advice", True, 0.95, 10 + i) for i in range(2)]
    )
    await detect_incidents(tenant, vs, verdicts, "RetireWell (guardrail-regression)")
    inc = await get_incident(tenant, "inc_" + __import__("hashlib").sha256(
        f"{vs.id}:no_financial_advice".encode()).hexdigest()[:12])
    assert inc is not None
    # finance_guardrail_v1 governs no_financial_advice, scoped to agent ~"retire".
    assert inc.policy == "finance_guardrail_v1"
    assert inc.band is None  # regulated agent → always escalate, no auto-ship band
    assert inc.baseline_trace is not None and "pass" in inc.baseline_trace.meta


@pytest.mark.asyncio
async def test_median_mttr_is_real_or_dash():
    """MTTR is computed from opened_at→resolved_at, never a fabricated constant:
    a clean tenant with no resolved incidents reports '—'."""
    from datetime import timedelta

    from eeof_core.models import SelfHealIncident
    from eeof_core.models.common import iso, utcnow
    from self_heal_svc.store import _median_mttr

    assert _median_mttr([]) == "—"
    opened = utcnow()
    incs = [
        SelfHealIncident(
            id="i1", agent="a", failure="f", status="resolved",
            opened_at=iso(opened), resolved_at=iso(opened + timedelta(minutes=12)),
        ),
        SelfHealIncident(
            id="i2", agent="a", failure="f", status="resolved",
            opened_at=iso(opened), resolved_at=iso(opened + timedelta(minutes=8)),
        ),
    ]
    assert _median_mttr(incs) == "10m"  # median of 8m and 12m
