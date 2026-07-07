"""observability-svc — trace.events ingest + evidence-pack assembly job.

Ingest is a durable stream subscriber (not a job): every `trace.events.<run_id>`
message is folded into its run's batch aggregate. Evidence-pack assembly is the
one async job, consumed off `obs.jobs`.
"""

from __future__ import annotations

from eeof_core.dataplane import get_blob, get_bus, get_table, keys
from eeof_core.ids import new_id
from eeof_core.models import EvidencePack, Job, VerdictSet
from eeof_core.worker import BaseWorker

from .store import evaluate_gate, record_trace_event, save_evidence


async def start_ingest() -> None:
    """Bind the durable TRACES consumer."""
    await get_bus().subscribe("trace.events.>", record_trace_event)


class EvidenceWorker(BaseWorker):
    subject = "obs.jobs"
    durable = "obs-workers"
    stage = "obs"

    async def handle(self, job: Job) -> dict:
        inputs = job.inputs
        candidate = inputs["candidate"]
        vs_ids: list[str] = inputs.get("verdict_set_ids") or [candidate]
        title = inputs.get("title", "Evaluation evidence pack")

        await self.progress(job, 1, 3, "gathering")
        gate = await evaluate_gate(job.tenant, vs_ids[0])

        sets = []
        for vs_id in vs_ids:
            row = await get_table().get(keys.verdictset_pk(job.tenant), keys.verdictset_sk(vs_id))
            if row:
                sets.append(VerdictSet.model_validate(row["data"]).model_dump(mode="json"))

        await self.progress(job, 2, 3, "assembling")
        pack_id = new_id("evidence")
        document = {
            "pack_id": pack_id,
            "candidate": candidate,
            "title": title,
            "gate": gate.model_dump(mode="json"),
            "verdict_sets": sets,
            "issued_at": job.updated_at,
        }
        blob_key = f"evidence/{job.tenant}/{pack_id}.json"
        uri, sha = await get_blob().put_json(blob_key, document)

        pack = EvidencePack(
            id=pack_id,
            tenant=job.tenant,
            candidate=candidate,
            title=title,
            verdict_set_ids=vs_ids,
            gate=gate.model_dump(mode="json"),
            blob_uri=uri,
            sha256=sha,
        )
        await save_evidence(job.tenant, pack)
        await self.progress(job, 3, 3, "ready")
        return {"pack_id": pack_id, "decision": gate.decision, "pass_rate": gate.pass_rate}


worker = EvidenceWorker()
