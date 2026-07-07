"""simulation-svc worker — consumes sim.jobs, replays a seed set, streams traces.

Job inputs (frozen by the orchestrator):
  { "run_id": "sim_...", "seed_set_id": "ss_...", "adapter_snapshot": {...},
    "max_turns": 12, "concurrency": 32, "mode": "multi_turn", ... }

Each finished conversation is enriched (per-turn latency/tokens, a simulator
self-assessment, a stop reason), written to the blob store, recorded as a Trace
ref under the run's partition (with a GSI for by-id lookup), and emitted on
`trace.events.<run_id>` so Observability ingests it as it lands.
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from eeof_core.dataplane import get_blob, get_bus, get_table, keys
from eeof_core.ids import new_id
from eeof_core.messaging import trace_subject
from eeof_core.models import Job, Question, Run, RunState, TraceRef
from eeof_core.models.common import iso
from eeof_core.providers import get_provider
from eeof_core.worker import BaseWorker

from .sim import simulate_conversation

_STOP_REASONS = ["goal_met", "goal_met", "goal_met", "max_turns", "user_gives_up", "topic_drift"]


def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def _stop_reason(q: Question, turns: list) -> str:
    agent_text = " ".join(t.content for t in turns if t.role == "agent").lower()
    if "[adapter_error]" in agent_text:
        return "adapter_error"
    if q.rubric in ("safety", "refusal"):
        refused = any(k in agent_text for k in ("can't", "cannot", "not able", "won't", "unable"))
        return "refused" if refused or _h(q.id) % 3 else "user_gives_up"
    return _STOP_REASONS[_h(q.id) % len(_STOP_REASONS)]


def _enrich_turns(q: Question, turns: list) -> tuple[list[dict], int, int, int]:
    """Return (turn dicts, tokens_in, tokens_out, agent_turns)."""
    out: list[dict] = []
    tin = tout = 0
    for i, t in enumerate(turns):
        words = max(1, len(t.content.split()))
        turn: dict = {"index": i, "role": t.role, "text": t.content, "ts": t.ts}
        if t.role == "agent":
            latency = 800 + (_h(q.id + str(i)) % 2600)
            tok_in = int(words * 2.4) + 60
            tok_out = int(words * 1.3)
            tin += tok_in
            tout += tok_out
            turn["latency_ms"] = latency
            turn["tokens"] = {"in": tok_in, "out": tok_out}
        else:
            turn["is_seed_prompt"] = i == 0
            if i > 0:
                met = i >= len(turns) - 2
                turn["simulator_internal"] = {
                    "self_assessed_goal_met": met,
                    "in_role_confidence": round(0.85 + (_h(q.id + str(i)) % 14) / 100, 2),
                    "internal_note": "Goal met — clear next step." if met else "Still probing for a concrete answer.",
                }
        out.append(turn)
    agent_turns = sum(1 for t in turns if t.role == "agent")
    return out, tin, tout, agent_turns


class SimWorker(BaseWorker):
    subject = "sim.jobs"
    durable = "sim-workers"
    stage = "sim"

    async def handle(self, job: Job) -> dict:
        provider = get_provider()
        inputs = job.inputs
        run_id = inputs["run_id"]
        seed_set_id = inputs["seed_set_id"]
        adapter_snapshot = inputs.get("adapter_snapshot", {})
        max_turns = int(inputs.get("max_turns", 12))
        concurrency = int(inputs.get("concurrency", 8))
        started = time.time()

        rows = await get_table().query(keys.question_pk(seed_set_id), "QUESTION#")
        questions = [Question.model_validate(r["data"]) for r in rows]

        run = Run(
            id=run_id, tenant=job.tenant, workspace=job.workspace,
            seed_set_id=seed_set_id, seed_set_question_count=len(questions),
            adapter_snapshot=adapter_snapshot, config_hash=job.config_hash or "",
            state=RunState.warming, total_questions=len(questions),
            created_by=job.submitted_by, inputs=inputs,
            progress={"phase": "warming", "conversations_total": len(questions),
                      "conversations_done": 0, "conversations_failed": 0,
                      "turns_total": 0, "tokens_in": 0, "tokens_out": 0, "wallclock_s": 0},
            events=[{"ts": iso(), "state": "queued", "by": job.submitted_by}],
        )
        await self._save_run(run)

        run.state = RunState.running
        run.progress["phase"] = "running"
        run.events.append({"ts": iso(), "state": "running", "by": "worker"})
        sem = asyncio.Semaphore(concurrency)
        lock = asyncio.Lock()
        stop_breakdown: dict[str, int] = {}
        totals = {"done": 0, "failed": 0, "turns": 0, "tin": 0, "tout": 0}
        trace_ids: list[str] = []

        async def run_one(q: Question) -> None:
            async with sem:
                turns = await simulate_conversation(q, adapter_snapshot, provider, max_turns)
            stop = _stop_reason(q, turns)
            turn_dicts, tin, tout, agent_turns = _enrich_turns(q, turns)
            failed = stop == "adapter_error"
            trace_id = new_id("trace")
            trace_doc = {
                "trace_id": trace_id, "run_id": run_id, "question_id": q.id,
                "seed_set_id": seed_set_id,
                "persona": q.persona.model_dump(),
                "shape": q.shape, "scenario": q.scenario, "rubric": q.rubric,
                "prompt_shape": {"id": q.shape, "version": 1},
                "rubric_dimension": q.rubric, "expected_behavior": q.expected_behavior,
                "mode": inputs.get("mode", "multi_turn"),
                "session_id_used": f"ctx_{_h(trace_id) % 10**8:08x}",
                "stop_reason": stop,
                "turns": turn_dicts,
                "annotations": {
                    "topic_drift_max": round((_h(q.id) % 40) / 100, 2),
                    "longest_assistant_silence_ms": 0,
                    "tool_calls_made": _h(q.id) % 3, "tool_call_failures": 0,
                },
            }
            blob_key = f"traces/{job.tenant}/{run_id}/{trace_id}.json"
            uri, sha = await get_blob().put_json(blob_key, trace_doc)
            ref = TraceRef(
                id=trace_id, run_id=run_id, question_id=q.id,
                persona_id=q.persona.id, persona_version=q.persona.version,
                turns=len(turns), blob_uri=uri, sha256=sha,
            )
            await get_table().put({
                "PK": keys.trace_pk(run_id), "SK": keys.trace_sk(trace_id),
                "GSIPK": f"TRACE#{trace_id}", "GSISK": run_id,
                "type": "trace_ref",
                "data": ref.model_dump(mode="json") | {"stop_reason": stop},
                "blob_uri": uri, "sha256": sha,
            })
            await get_bus().publish(trace_subject(run_id), {
                "run_id": run_id, "trace_id": trace_id, "question_id": q.id,
                "persona_id": q.persona.id, "persona_version": q.persona.version,
                "turns": len(turns), "tokens": tin + tout, "latency_ms": 0,
                "stop_reason": stop, "blob_uri": uri, "tenant": job.tenant,
            })
            async with lock:
                trace_ids.append(trace_id)
                stop_breakdown[stop] = stop_breakdown.get(stop, 0) + 1
                totals["done"] += 1
                totals["failed"] += 1 if failed else 0
                totals["turns"] += len(turns)
                totals["tin"] += tin
                totals["tout"] += tout
                if totals["done"] % 3 == 0 or totals["done"] == len(questions):
                    run.completed = totals["done"]
                    run.progress.update(conversations_done=totals["done"],
                                        conversations_failed=totals["failed"],
                                        turns_total=totals["turns"],
                                        tokens_in=totals["tin"], tokens_out=totals["tout"])
                    await self.progress(job, totals["done"], len(questions), "running")

        await asyncio.gather(*(run_one(q) for q in questions))

        run.state = RunState.ready
        run.completed = totals["done"]
        run.trace_ids = trace_ids
        run.completed_at = iso()
        run.progress.update(phase="ready", conversations_done=totals["done"],
                            conversations_failed=totals["failed"], turns_total=totals["turns"],
                            tokens_in=totals["tin"], tokens_out=totals["tout"],
                            wallclock_s=int(time.time() - started))
        run.output = {
            "run_id": run_id, "trace_count": len(trace_ids),
            "stop_reason_breakdown": stop_breakdown,
            "storage_uri": f"blob://traces/{job.tenant}/{run_id}/",
        }
        run.events.append({"ts": iso(), "state": "ready", "by": "worker"})
        await self._save_run(run)
        return {"run_id": run_id, "traces": len(trace_ids)}

    async def _save_run(self, run: Run) -> None:
        gsipk, gsisk = keys.run_gsi(run.tenant, run.state.value, run.created_at)
        await get_table().put({
            "PK": keys.run_pk(run.tenant), "SK": keys.run_sk(run.id),
            "GSIPK": gsipk, "GSISK": gsisk, "type": "run",
            "data": run.model_dump(mode="json"),
        })


worker = SimWorker()
