"""Request → job translation: freeze inputs, dedupe, queue, return 202.

This is the orchestrator's async path. It does *not* run domain logic — it
validates, freezes immutable snapshots into the job envelope, writes the queued
Job record, publishes to the correct JOBS subject, and returns the job id.
"""

from __future__ import annotations

from eeof_core.dataplane import get_bus
from eeof_core.ids import new_id
from eeof_core.jobs import list_jobs, save_job
from eeof_core.messaging import SUBMIT_SUBJECT, config_hash
from eeof_core.models import Job, JobProgress, JobState, Principal


async def _find_by_hash(tenant: str, kind: str, chash: str) -> Job | None:
    for job in await list_jobs(tenant):
        if job.kind == kind and job.config_hash == chash:
            return job
    return None


async def submit_job(
    principal: Principal,
    *,
    kind: str,
    stage: str,
    inputs: dict,
    idempotency_key: str | None = None,
    extra_result: dict | None = None,
) -> dict:
    chash = config_hash(inputs)
    existing = await _find_by_hash(principal.tenant, kind, chash)
    if existing:  # idempotent — return the original job
        return _accepted(existing, extra_result)

    job = Job(
        job_id=new_id("job"),
        tenant=principal.tenant,
        workspace=principal.workspace,
        kind=kind,
        stage=stage,
        state=JobState.queued,
        progress=JobProgress(phase="queued"),
        idempotency_key=idempotency_key,
        config_hash=chash,
        inputs=inputs,
        submitted_by=principal.subject,
    )
    await save_job(job)

    envelope = job.model_dump(mode="json")
    await get_bus().publish_job(SUBMIT_SUBJECT[kind], envelope)
    return _accepted(job, extra_result)


def _accepted(job: Job, extra_result: dict | None) -> dict:
    payload = {"job_id": job.job_id, "state": job.state.value}
    # Surface pre-allocated resource ids (e.g. run_id) inline per the spec.
    if extra_result:
        payload.update(extra_result)
    elif job.result:
        payload.update(job.result)
    return payload
