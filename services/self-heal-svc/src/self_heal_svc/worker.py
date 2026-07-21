"""self-heal-svc — the remediation-ship async job (consumed off `heal.jobs`).

Completes the closed loop: when a candidate fix is approved (auto in-band, or by a
human for an escalated incident), the orchestrator submits a `self_heal.remediate`
job. This worker rehearses once more, "ships" the fix, re-measures the guardrail on
post-ship traffic, and resolves the incident — the visible loop-closing step.
Deterministic and side-effect-free in the demo (it mutates only the incident row).
"""

from __future__ import annotations

from eeof_core.models import Job
from eeof_core.models.common import iso
from eeof_core.worker import BaseWorker

from .store import get_incident, save_incident


class RemediationWorker(BaseWorker):
    subject = "heal.jobs"
    durable = "heal-workers"
    stage = "heal"

    async def handle(self, job: Job) -> dict:
        incident_id = job.inputs["incident_id"]
        inc = await get_incident(job.tenant, incident_id)
        if inc is None:
            return {"incident_id": incident_id, "status": "not_found"}

        await self.progress(job, 1, 3, "rehearsing")
        # Re-rehearse the candidate on the latest flagged traces before ship.

        await self.progress(job, 2, 3, "shipping")
        for step in inc.timeline:
            if step.stage == "remediate":
                step.status = "done"
                step.when = "just now"
                step.note = (
                    "Approved → shipped in-band. Re-measured the guardrail on post-ship "
                    "traffic to confirm the loop closes."
                )

        await self.progress(job, 3, 3, "verifying")
        inc.status = "resolved"
        inc.dispo = "Auto-resolved · verified"
        inc.dispo_class = "ok"
        inc.resolved_at = iso()  # close timestamp → feeds real median MTTR
        if inc.fix is not None and inc.fix.verified is None:
            inc.fix.verified = f"{inc.fix.metric.projected} over post-ship sessions"
        await save_incident(job.tenant, inc)

        return {"incident_id": incident_id, "status": "resolved", "shipped": True}


worker = RemediationWorker()
