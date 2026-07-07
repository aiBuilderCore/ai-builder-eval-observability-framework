"""Observability control-plane store — batches, monitors, incidents, gate, evidence.

Per the spec, high-volume span telemetry is *not* in the single table; the
control-plane metadata below is. Batch rows are lightweight per-run ingest
aggregates kept for the dashboard.
"""

from __future__ import annotations

from eeof_core.dataplane import get_table, keys
from eeof_core.ids import new_id
from eeof_core.models import (
    Batch,
    EvidencePack,
    GateDecision,
    Incident,
    Monitor,
    MonitorDraft,
    VerdictSet,
    iso,
)


def _batch_pk(tenant: str) -> str:
    return f"TENANT#{tenant}#BATCH"


def _batch_sk(run_id: str) -> str:
    return f"BATCH#{run_id}"


async def record_trace_event(evt: dict) -> None:
    """Fold a streamed trace event into its run's batch aggregate."""
    tenant = evt.get("tenant", "acme")
    run_id = evt["run_id"]
    row = await get_table().get(_batch_pk(tenant), _batch_sk(run_id))
    if row:
        batch = Batch.model_validate(row["data"])
    else:
        batch = Batch(run_id=run_id, tenant=tenant)
    batch.traces += 1
    batch.tokens += int(evt.get("tokens", 0))
    batch.last_seen = iso()
    await get_table().put(
        {
            "PK": _batch_pk(tenant),
            "SK": _batch_sk(run_id),
            "type": "batch",
            "data": batch.model_dump(mode="json"),
        }
    )


async def list_batches(tenant: str) -> list[Batch]:
    rows = await get_table().query(_batch_pk(tenant), "BATCH#")
    return [Batch.model_validate(r["data"]) for r in rows]


# --- Monitors ---
async def create_monitor(tenant: str, draft: MonitorDraft) -> Monitor:
    monitor = Monitor(id=new_id("monitor"), **draft.model_dump())
    gsipk, gsisk = keys.monitor_gsi(tenant, monitor.env, monitor.version)
    await get_table().put(
        {
            "PK": keys.monitor_pk(tenant),
            "SK": keys.monitor_sk(monitor.id, monitor.version),
            "GSIPK": gsipk,
            "GSISK": gsisk,
            "type": "monitor",
            "data": monitor.model_dump(mode="json"),
        }
    )
    return monitor


async def list_monitors(tenant: str) -> list[Monitor]:
    rows = await get_table().query(keys.monitor_pk(tenant), "MONITOR#")
    return [Monitor.model_validate(r["data"]) for r in rows]


async def list_incidents(tenant: str, state: str | None = None) -> list[Incident]:
    gsipk, _ = keys.incident_gsi(tenant, "", "")
    rows = await get_table().query_gsi(gsipk, f"{state}#" if state else None)
    return [Incident.model_validate(r["data"]) for r in rows]


# --- Deploy gate ---
async def evaluate_gate(tenant: str, candidate: str, threshold: float = 0.8) -> GateDecision:
    """`candidate` is a verdict_set_id here; pass iff its pass_rate >= threshold."""
    row = await get_table().get(keys.verdictset_pk(tenant), keys.verdictset_sk(candidate))
    if not row:
        return GateDecision(candidate=candidate, decision="no_data", threshold=threshold)
    vset = VerdictSet.model_validate(row["data"])
    decision = "pass" if vset.pass_rate >= threshold else "fail"
    return GateDecision(
        candidate=candidate,
        decision=decision,
        pass_rate=vset.pass_rate,
        threshold=threshold,
        verdict_set_ids=[candidate],
    )


# --- Evidence packs ---
async def save_evidence(tenant: str, pack: EvidencePack) -> None:
    gsipk, gsisk = keys.evidence_gsi(tenant, pack.issued_at)
    await get_table().put(
        {
            "PK": keys.evidence_pk(tenant),
            "SK": keys.evidence_sk(pack.id),
            "GSIPK": gsipk,
            "GSISK": gsisk,
            "type": "evidence_pack",
            "data": pack.model_dump(mode="json"),
            "blob_uri": pack.blob_uri,
        }
    )


async def get_evidence(tenant: str, pack_id: str) -> EvidencePack | None:
    row = await get_table().get(keys.evidence_pk(tenant), keys.evidence_sk(pack_id))
    return EvidencePack.model_validate(row["data"]) if row else None


async def list_evidence(tenant: str) -> list[EvidencePack]:
    gsipk, _ = keys.evidence_gsi(tenant, "")
    rows = await get_table().query_gsi(gsipk)
    return [EvidencePack.model_validate(r["data"]) for r in rows]


async def list_calibration(tenant: str) -> list[dict]:
    """Latest judge-calibration record per judge (written by evaluation-svc)."""
    rows = await get_table().query(f"TENANT#{tenant}#CALIBRATION", "CALIBRATION#")
    latest: dict[str, dict] = {}
    for r in rows:
        rec = r["data"]
        cur = latest.get(rec["judge_ref"])
        if cur is None or rec["ts"] > cur["ts"]:
            latest[rec["judge_ref"]] = rec
    return sorted(latest.values(), key=lambda x: x["judge_ref"])
