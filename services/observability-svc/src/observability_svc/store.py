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
    # Fold the trace's OpenInference span-kind counts into the run's histogram so
    # the batch-detail kind chart + the dashboard "spans" pill read from real
    # aggregates without re-scanning every trace blob.
    for kind, n in (evt.get("span_kinds") or {}).items():
        batch.kind_histogram[kind] = batch.kind_histogram.get(kind, 0) + int(n)
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
async def _verdictset_pass_rate(tenant: str, vs_id: str) -> float | None:
    row = await get_table().get(keys.verdictset_pk(tenant), keys.verdictset_sk(vs_id))
    return VerdictSet.model_validate(row["data"]).pass_rate if row else None


async def evaluate_gate(
    tenant: str, candidate: str, threshold: float = 0.8, baseline: str | None = None
) -> GateDecision:
    """`candidate` is a verdict_set_id; pass iff its pass_rate >= threshold.

    When `baseline` (another verdict_set_id) is supplied, the decision becomes a
    real head-to-head: the response carries the baseline pass_rate and the delta
    (candidate − baseline) so the gate is a comparison, not a bare threshold check.
    """
    cand_rate = await _verdictset_pass_rate(tenant, candidate)
    if cand_rate is None:
        return GateDecision(candidate=candidate, decision="no_data", threshold=threshold)

    base_rate = await _verdictset_pass_rate(tenant, baseline) if baseline else None
    decision = "pass" if cand_rate >= threshold else "fail"
    return GateDecision(
        candidate=candidate,
        decision=decision,
        pass_rate=cand_rate,
        threshold=threshold,
        verdict_set_ids=[candidate],
        baseline=baseline if base_rate is not None else None,
        baseline_pass_rate=base_rate,
        delta=round(cand_rate - base_rate, 4) if base_rate is not None else None,
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
    """Latest judge-calibration record per judge, enriched with the real rolling
    κ series (every prior calibration sample for that judge, oldest→newest, capped
    to the last 30). Each calibration record is written by evaluation-svc on every
    scoring run, so the series fills in as the pipeline runs repeatedly."""
    rows = await get_table().query(f"TENANT#{tenant}#CALIBRATION", "CALIBRATION#")
    history: dict[str, list[dict]] = {}
    for r in rows:
        rec = r["data"]
        history.setdefault(rec["judge_ref"], []).append(rec)

    out: list[dict] = []
    for judge_ref, recs in history.items():
        recs.sort(key=lambda x: x["ts"])
        latest = dict(recs[-1])
        latest["series"] = [round(float(x.get("kappa", 0.0)), 3) for x in recs][-30:]
        latest["sample_count"] = len(recs)
        out.append(latest)
    return sorted(out, key=lambda x: x["judge_ref"])
