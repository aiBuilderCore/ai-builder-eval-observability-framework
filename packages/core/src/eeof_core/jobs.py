"""Uniform Job lifecycle helpers, shared by the orchestrator and every worker.

A Job is persisted in the single table (JOB keys) and its live progress is both
pushed to the STATUS bus and snapshotted into the `job_progress` KV bucket, so a
reconnecting WebSocket gets current state without replaying the stream.
"""

from __future__ import annotations

from .dataplane import get_bus, get_table, keys
from .messaging import status_subject
from .models.common import Job, JobState, iso
from .providers.base import ScoreResult  # noqa: F401  (re-export convenience)

KV_BUCKET = "job_progress"


def _item(job: Job) -> dict:
    gsipk, gsisk = keys.job_gsi(job.tenant, job.state.value, job.updated_at)
    return {
        "PK": keys.job_pk(job.tenant),
        "SK": keys.job_sk(job.job_id),
        "GSIPK": gsipk,
        "GSISK": gsisk,
        "type": "job",
        "data": job.model_dump(mode="json"),
    }


async def save_job(job: Job) -> None:
    job.updated_at = iso()
    await get_table().put(_item(job))


async def get_job(tenant: str, job_id: str) -> Job | None:
    it = await get_table().get(keys.job_pk(tenant), keys.job_sk(job_id))
    return Job.model_validate(it["data"]) if it else None


async def list_jobs(tenant: str, state: str | None = None) -> list[Job]:
    gsipk, _ = keys.job_gsi(tenant, "", "")
    items = await get_table().query_gsi(gsipk, f"{state}#" if state else None)
    return [Job.model_validate(i["data"]) for i in items]


async def push_status(job: Job) -> None:
    """Persist, snapshot to KV, and fan out on the STATUS bus."""
    await save_job(job)
    bus = get_bus()
    snapshot = {
        "type": "status",
        "job_id": job.job_id,
        "state": job.state.value,
        "progress": job.progress.model_dump(),
        "result": job.result,
        "error": job.error,
    }
    await bus.kv_put(KV_BUCKET, job.job_id, snapshot)
    await bus.publish(status_subject(job.stage, job.job_id), snapshot)


async def fail_job(job: Job, code: str, message: str) -> None:
    job.state = JobState.failed
    job.error = {"code": code, "message": message}
    await push_status(job)
