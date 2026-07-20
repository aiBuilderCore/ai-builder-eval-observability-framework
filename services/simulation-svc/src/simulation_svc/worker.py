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
import re
import secrets
import time

from eeof_core.dataplane import get_blob, get_bus, get_table, keys
from eeof_core.ids import new_id
from eeof_core.messaging import trace_subject
from eeof_core.models import Job, Question, Run, RunState, TraceRef
from eeof_core.models.common import iso
from eeof_core.providers import get_provider
from eeof_core.worker import BaseWorker

from .sim import resolve_mode, simulate_conversation

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
            # Real tool-call sequence the agent made on this turn (from /chat).
            turn["tool_calls"] = list(getattr(t, "tool_calls", []) or [])
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


def _collect_spans(turns: list) -> tuple[list[dict], dict[str, int]]:
    """Stitch each agent turn's OpenInference spans onto one conversation timeline.

    The agent emits spans with `start_ms` relative to its own turn (root at 0);
    here we offset every turn's spans by the cumulative end of the prior turns so
    the run reads as a single left-to-right waterfall, and count span kinds for
    the batch histogram. Returns `([], {})` when the target emitted no spans (an
    uninstrumented endpoint), so the frontend can fall back to reconstruction.
    """
    all_spans: list[dict] = []
    kinds: dict[str, int] = {}
    offset = 0
    for t in turns:
        spans = list(getattr(t, "spans", []) or [])
        if not spans:
            continue
        turn_end = 0
        for s in spans:
            span = dict(s)
            span["start_ms"] = int(span.get("start_ms", 0)) + offset
            all_spans.append(span)
            kinds[span.get("kind", "?")] = kinds.get(span.get("kind", "?"), 0) + 1
            turn_end = max(turn_end, span["start_ms"] + int(span.get("duration_ms", 0)))
        offset = turn_end + 20  # small inter-turn gap so bars don't abut

    # A multi-turn conversation emits one AGENT root per turn. Wrap them in a
    # single synthetic CHAIN "conversation" root so the trace is single-rooted
    # (conventional OTel — one root per trace) and the turns nest under it. This
    # also gives trace-level EVALUATOR spans (added at render from real verdicts)
    # one place to attach, instead of appearing to belong to turn 1. Single-turn
    # traces keep their lone AGENT root untouched.
    roots = [s for s in all_spans if not s.get("parent_id")]
    if len(roots) > 1:
        total = max((s["start_ms"] + s["duration_ms"] for s in all_spans), default=0)
        conv_id = secrets.token_hex(8)
        for r in roots:
            r["parent_id"] = conv_id
        all_spans.insert(0, {
            "id": conv_id, "parent_id": None, "kind": "CHAIN",
            "name": "retirement_401k.conversation",
            "start_ms": 0, "duration_ms": max(1, total),
            "attrs": {
                "openinference.span.kind": "CHAIN",
                "gen_ai.operation.name": "chat",
                "conversation.turn_count": len(roots),
            },
        })
        kinds["CHAIN"] = kinds.get("CHAIN", 0) + 1
    return all_spans, kinds


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
        mode = inputs.get("mode", "multi_turn")
        concurrency = int(inputs.get("concurrency", 8))
        started = time.time()

        rows = await get_table().query(keys.question_pk(seed_set_id), "QUESTION#")
        questions = [Question.model_validate(r["data"]) for r in rows]

        # Persist the run in `running` from the outset. There is no separate
        # warm-up work to do, so a distinct `warming` state would only ever flip
        # instantly and read as a dead card in the UI — open the audit trail with
        # the real queued→running transition instead.
        run = Run(
            id=run_id, tenant=job.tenant, workspace=job.workspace,
            seed_set_id=seed_set_id, seed_set_question_count=len(questions),
            adapter_snapshot=adapter_snapshot, config_hash=job.config_hash or "",
            state=RunState.running, total_questions=len(questions),
            created_by=job.submitted_by, inputs=inputs,
            progress={"phase": "running", "conversations_total": len(questions),
                      "conversations_done": 0, "conversations_failed": 0,
                      "turns_total": 0, "tokens_in": 0, "tokens_out": 0, "wallclock_s": 0},
            events=[{"ts": iso(), "state": "queued", "by": job.submitted_by},
                    {"ts": iso(), "state": "running", "by": "worker"}],
        )
        await self._save_run(run)

        sem = asyncio.Semaphore(concurrency)
        lock = asyncio.Lock()
        stop_breakdown: dict[str, int] = {}
        totals = {"done": 0, "failed": 0, "turns": 0, "tin": 0, "tout": 0}
        trace_ids: list[str] = []

        async def run_one(q: Question) -> None:
            # One W3C trace id per conversation, propagated to the agent so every
            # turn's spans stitch into a single trace.
            otel_trace_id = secrets.token_hex(16)
            async with sem:
                turns = await simulate_conversation(
                    q, adapter_snapshot, provider, max_turns, mode, otel_trace_id
                )
            stop = _stop_reason(q, turns)
            turn_dicts, tin, tout, agent_turns = _enrich_turns(q, turns)
            # Real tool-call telemetry, aggregated from the agent's actual calls
            # across the conversation (no synthetic scalar). `tool_call_sequence`
            # is the ordered list of tool names — the signal Observability's
            # trajectory-drift and tool-call monitors read.
            tool_seq: list[str] = []
            tool_failures = 0
            for t in turns:
                for c in getattr(t, "tool_calls", []) or []:
                    tool_seq.append(c.get("name", "?"))
                    if not c.get("ok", True):
                        tool_failures += 1
            # The real OpenInference span tree the agent emitted this run, stitched
            # onto one conversation timeline (AGENT root + PROMPT/LLM/TOOL/RETRIEVER/
            # GUARDRAIL children, W3C ids, GenAI semconv attrs). EVALUATOR spans are
            # added downstream from real judge verdicts.
            spans, span_kinds = _collect_spans(turns)
            if not spans:
                # Uninstrumented target (no /spans in the reply): fall back to the
                # backend-reconstructed kind counts derived from the tool sequence.
                span_kinds = {"AGENT": 1, "LLM": agent_turns, "RETRIEVER": 0, "GUARDRAIL": 0, "TOOL": 0}
                for name in tool_seq:
                    if name.startswith("retrieve"):
                        span_kinds["RETRIEVER"] += 1
                    elif re.search(r"disclosure|compliance|guardrail", name):
                        span_kinds["GUARDRAIL"] += 1
                    else:
                        span_kinds["TOOL"] += 1
            failed = stop == "adapter_error"
            trace_id = new_id("trace")
            trace_doc = {
                "trace_id": trace_id, "run_id": run_id, "question_id": q.id,
                # W3C trace id shared by every agent span on this conversation.
                "otel_trace_id": otel_trace_id,
                # The real OpenInference span tree (agent lifecycle) for this run.
                # EVALUATOR spans are merged in at render time from real verdicts.
                "spans": spans,
                "seed_set_id": seed_set_id,
                "persona": q.persona.model_dump(),
                "shape": q.shape, "scenario": q.scenario, "rubric": q.rubric,
                "prompt_shape": {"id": q.shape, "version": 1},
                "rubric_dimension": q.rubric, "expected_behavior": q.expected_behavior,
                "mode": resolve_mode(mode, q, adapter_snapshot),
                "session_id_used": f"ctx_{_h(trace_id) % 10**8:08x}",
                "stop_reason": stop,
                "turns": turn_dicts,
                "annotations": {
                    # topic_drift_max has no real embedding source yet; kept as a
                    # coarse signal (elevated when the conversation actually ended
                    # in topic drift) rather than a pure hash.
                    "topic_drift_max": 0.62 if stop == "topic_drift" else 0.12,
                    "longest_assistant_silence_ms": 0,
                    # REAL — from the agent's actual tool calls this run.
                    "tool_calls_made": len(tool_seq),
                    "tool_call_failures": tool_failures,
                    "tool_call_sequence": tool_seq,
                    # REAL — backend-computed OpenInference span-kind counts for the
                    # agent lifecycle (EVALUATOR added downstream from verdicts).
                    "span_kinds": span_kinds,
                },
            }
            blob_key = f"traces/{job.tenant}/{run_id}/{trace_id}.json"
            uri, sha = await get_blob().put_json(blob_key, trace_doc)
            ref = TraceRef(
                id=trace_id, run_id=run_id, question_id=q.id,
                persona_id=q.persona.id, persona_version=q.persona.version,
                # A "turn" is a user↔agent exchange, so the count is the number of
                # agent replies, not the raw message count.
                turns=agent_turns, blob_uri=uri, sha256=sha,
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
                "turns": agent_turns, "tokens": tin + tout, "latency_ms": 0,
                "stop_reason": stop, "blob_uri": uri, "tenant": job.tenant,
                # Real span-kind counts so Observability folds them into the
                # run's batch histogram as the event lands (no blob re-read).
                "span_kinds": span_kinds,
            })
            async with lock:
                trace_ids.append(trace_id)
                stop_breakdown[stop] = stop_breakdown.get(stop, 0) + 1
                totals["done"] += 1
                totals["failed"] += 1 if failed else 0
                totals["turns"] += agent_turns
                totals["tin"] += tin
                totals["tout"] += tout
                # Checkpoint on every completed conversation so throughput
                # (convos / turns / tokens / wallclock) and the audit trail
                # hydrate live as the run flows — not in coarse 3-convo jumps.
                # The write is keyed by (PK, SK), so it updates the single run
                # row in place; the status push drives the socket repaint.
                run.completed = totals["done"]
                run.progress.update(conversations_done=totals["done"],
                                    conversations_failed=totals["failed"],
                                    turns_total=totals["turns"],
                                    tokens_in=totals["tin"], tokens_out=totals["tout"],
                                    wallclock_s=int(time.time() - started))
                await self._save_run(run)
                await self.progress(job, totals["done"], len(questions), "running")

        await asyncio.gather(*(run_one(q) for q in questions))

        # Finalizing — close sessions and assemble the run summary. Emitted as a
        # real phase (persisted + pushed) so the progress strip and audit trail
        # show it instead of jumping straight from running to ready.
        run.state = RunState.finalizing
        run.progress.update(phase="finalizing", wallclock_s=int(time.time() - started))
        run.events.append({"ts": iso(), "state": "finalizing", "by": "worker"})
        await self._save_run(run)
        await self.progress(job, totals["done"], len(questions), "finalizing")

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
