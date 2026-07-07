"""Base async worker.

Binds a durable work-queue consumer on a JOBS subject, rehydrates the Job,
drives its lifecycle (running → finalizing → ready/failed), and republishes
progress. Subclasses implement `handle(job)`; they call `self.progress(...)` to
checkpoint. Idempotency: a redelivered job whose `config_hash` already produced
output is skipped (subclasses set `job.result` on the existing record).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .dataplane import get_bus
from .jobs import fail_job, get_job, push_status
from .models.common import Job, JobProgress, JobState


class BaseWorker(ABC):
    #: JOBS subject to consume, e.g. "sim.jobs"
    subject: str
    #: durable consumer name
    durable: str
    #: short stage tag used in status subjects, e.g. "sim"
    stage: str

    async def start(self) -> None:
        await get_bus().bind_worker(self.subject, self.durable, self._on_message)

    async def _on_message(self, envelope: dict) -> None:
        job_id = envelope["job_id"]
        tenant = envelope["tenant"]
        job = await get_job(tenant, job_id)
        if job is None:  # envelope arrived before the record; reconstruct
            job = Job.model_validate(envelope | {"stage": self.stage})
        if job.state in (JobState.ready, JobState.shipped) and job.result:
            return  # idempotent no-op — output already exists
        try:
            job.state = JobState.running
            job.progress = JobProgress(phase="running")
            await push_status(job)
            result = await self.handle(job)
            job.result = result
            job.state = JobState.ready
            job.progress.phase = "ready"
            await push_status(job)
        except Exception as e:  # noqa: BLE001 — surface any failure as a failed job
            await fail_job(job, "worker_error", str(e))

    async def progress(self, job: Job, done: int, total: int, phase: str = "running") -> None:
        job.progress = JobProgress(done=done, total=total, phase=phase)
        await push_status(job)

    @abstractmethod
    async def handle(self, job: Job) -> dict:
        """Do the work; return the job result ref (e.g. {'run_id': 'sim_...'})."""
