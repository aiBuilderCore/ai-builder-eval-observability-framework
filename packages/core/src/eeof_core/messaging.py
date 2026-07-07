"""JetStream subject map, stream layout, and the job envelope.

Mirrors the framework Messaging spec: three streams (JOBS/STATUS/TRACES),
hierarchical subjects so each worker binds exactly the slice it owns.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# --- Streams ---
STREAM_JOBS = "JOBS"
STREAM_STATUS = "STATUS"
STREAM_TRACES = "TRACES"

STREAMS: dict[str, list[str]] = {
    # obs.jobs carries evidence-pack assembly — the one Observability async job.
    STREAM_JOBS: ["qgen.jobs", "sim.jobs", "eval.jobs", "obs.jobs"],
    STREAM_STATUS: ["status.>"],
    STREAM_TRACES: ["trace.events.>"],
}

# --- Submission subjects (JOBS stream), keyed by job kind ---
SUBMIT_SUBJECT = {
    "qgen.generate": "qgen.jobs",
    "simulation.run": "sim.jobs",
    "evaluation.score": "eval.jobs",
    "observability.evidence": "obs.jobs",
}


def status_subject(stage: str, job_id: str) -> str:
    """status.<stage>.<job_id> — one worker's progress feed for one job."""
    return f"status.{stage}.{job_id}"


def status_wildcard(stage: str = "*") -> str:
    return f"status.{stage}.*"


def trace_subject(run_id: str) -> str:
    """trace.events.<run_id> — one message per finished conversation."""
    return f"trace.events.{run_id}"


def config_hash(inputs: dict[str, Any]) -> str:
    """Stable dedupe key over a job's frozen inputs (order-independent)."""
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
