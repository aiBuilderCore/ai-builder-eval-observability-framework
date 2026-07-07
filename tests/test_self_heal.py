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

TENANT = "acme"
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
    assert len(await list_policies(TENANT)) == 3


@pytest.mark.asyncio
async def test_summary_counts_open_incidents():
    s = await summary(TENANT)
    # 6 seeded, one resolved (INC-988) => 5 open.
    assert s.open_incidents == 5
    assert s.active_policies == 3


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
