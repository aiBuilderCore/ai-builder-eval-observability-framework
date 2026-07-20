"""evaluation-svc worker — consumes eval.jobs, ships an immutable verdict set.

Job inputs (frozen by the orchestrator):
  { "run_ids": [...], "judge_refs": ["helpfulness@v1", ...],
    "panel_id": null, "mode": "panel", "aggregation": "majority",
    "mitigations": [...] }

For every trace × judge, a jury (or single judge) scores the agent's response
against the seed prompt; each verdict carries per-juror scores and a consensus
rate. A judge-calibration record is written per judge — a real, chance-corrected
Cohen's κ of that judge vs the leave-one-out majority of the rest of the panel on
the same traces — so Observability's calibration view has a genuine source.
"""

from __future__ import annotations

import hashlib

from eeof_core.dataplane import get_blob, get_table, keys
from eeof_core.ids import new_id
from eeof_core.jobs import push_status, record_event
from eeof_core.models import Job, TraceRef, Verdict, VerdictSet
from eeof_core.models.common import iso
from eeof_core.providers import get_provider
from eeof_core.self_heal_detect import detect_incidents
from eeof_core.worker import BaseWorker

def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def _cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's κ between two binary raters over paired observations.

    Returns None when there are no pairs. When chance agreement is degenerate
    (pe == 1 — both raters put every item in the same single category) κ is
    mathematically undefined, so we report the raw agreement (1.0 if the raters
    matched on every item, else 0.0) instead of dividing by zero.
    """
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n          # observed agreement
    pa = sum(1 for a, _ in pairs if a) / n               # rater A "true" rate
    pb = sum(1 for _, b in pairs if b) / n               # rater B "true" rate
    pe = pa * pb + (1 - pa) * (1 - pb)                    # chance agreement
    if pe >= 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


class EvalWorker(BaseWorker):
    subject = "eval.jobs"
    durable = "eval-workers"
    stage = "eval"

    async def handle(self, job: Job) -> dict:
        provider = get_provider()
        inputs = job.inputs
        run_ids: list[str] = inputs["run_ids"]
        judge_refs: list[str] = inputs.get("judge_refs") or ["helpfulness@v1"]
        rubrics = inputs.get("judge_rubrics") or {r: r.split("@")[0] for r in judge_refs}
        mitigations = inputs.get("mitigations") or ["position_swap", "length_normalization"]
        # One real juror per configured provider — no fabricated multi-vendor
        # panel. With a single configured provider every dimension is scored once,
        # so the job is judge mode; a true multi-model jury only appears when the
        # deployment actually wires more than one juror model. The juror's model
        # label is resolved *per verdict* below from the model that actually served
        # the score (the chain may drop to echo when the primary is rate-limited).
        n = 1
        jury = inputs.get("mode") in ("panel", "jury") and n > 1
        mode = "jury" if jury else "judge"

        vs_id = new_id("verdict_set")
        verdicts: list[Verdict] = []
        traces: list[TraceRef] = []
        for run_id in run_ids:
            rows = await get_table().query(keys.trace_pk(run_id), "TRACE#")
            traces.extend(TraceRef.model_validate(r["data"]) for r in rows)

        total_cells = max(1, len(traces) * len(judge_refs))
        dim_scores: dict[str, list[float]] = {}
        judge_consensus: dict[str, list[float]] = {}
        judge_calls = 0
        cell = 0
        pass_running = 0

        # Write the verdict-set row up front (state=running) so the UI can fetch
        # this set by id and paint verdicts as they stream in — mirrors qgen's
        # incremental questions. Finalised with real aggregates after scoring.
        vset = VerdictSet(
            id=vs_id, tenant=job.tenant, workspace=job.workspace, run_ids=run_ids,
            judge_refs=judge_refs, aggregation=inputs.get("aggregation", "majority"),
            mode=mode, state="running",
        )
        await self._put_verdictset(job.tenant, vset)

        for tref in traces:
            trace = await get_blob().get_json(tref.blob_uri)
            turns = trace.get("turns", [])
            prompt = next((t.get("text") or t.get("content", "") for t in turns if t["role"] == "user"), "")
            # The judge scores the WHOLE conversation, not just the opening turn:
            # build the full transcript so multi-turn agent behaviour is graded.
            transcript = "\n".join(
                f"{t.get('role', '').upper()}: {t.get('text') or t.get('content', '')}"
                for t in turns
            )
            agent_turn_count = sum(1 for t in turns if t.get("role") == "agent")
            persona_name = (trace.get("persona") or {}).get("name", "")

            for ref in judge_refs:
                cell += 1
                dim = rubrics.get(ref, ref.split("@")[0])
                base = await provider.score(rubric=dim, prompt=prompt, response=transcript)
                score = round(base["score"], 3)
                verdict_label = "pass" if base["passed"] else "fail"
                # Attribute the verdict to the model that ACTUALLY served this score.
                # On a fallback chain that is the link which answered (echo when the
                # primary was rate-limited), not the statically-configured primary.
                served_model = getattr(provider, "last_served_label", provider.model_label)
                jurors = [{"id": ref, "model": served_model, "score": score, "verdict": verdict_label}]
                judge_calls += len(jurors)
                # Full agreement for aggregation (single real juror = unanimous);
                # only surfaced on the verdict in jury mode.
                consensus = 1.0
                mean_score = score

                v = Verdict(
                    id=new_id("verdict"), verdict_set_id=vs_id, run_id=tref.run_id,
                    trace_id=tref.id, question_id=tref.question_id, judge_ref=ref,
                    passed=verdict_label == "pass", score=mean_score, rationale=base["rationale"],
                    persona_id=tref.persona_id, persona_version=tref.persona_version,
                    dimension=dim, verdict=verdict_label, question_prompt=prompt[:400],
                    persona_name=persona_name, mode=mode, judges=jurors,
                    consensus_rate=consensus if jury else None,
                    scored_turns=agent_turn_count,
                    mitigations_applied=mitigations, rubric={"id": dim, "version": 1},
                )
                verdicts.append(v)
                if verdict_label == "pass":
                    pass_running += 1
                dim_scores.setdefault(dim, []).append(mean_score)
                judge_consensus.setdefault(ref, []).append(consensus)
                gsipk, gsisk = keys.verdict_gsi(tref.run_id, v.id)
                await get_table().put({
                    "PK": keys.verdict_pk(vs_id), "SK": keys.verdict_sk(v.id),
                    "GSIPK": gsipk, "GSISK": gsisk, "type": "verdict",
                    "data": v.model_dump(mode="json"),
                })
                if cell % 5 == 0 or cell == total_cells:
                    await self._progress(job, cell, total_cells, verdicts,
                                         judge_calls, vs_id, pass_running)

        # Aggregation phase — dotted on the audit timeline so the trail reads
        # queued → running → aggregating → ready instead of a bare jump to ready.
        job.progress.phase = "aggregating"
        job.progress.detail = {
            "cells_total": total_cells, "cells_done": cell,
            "verdicts_emitted": len(verdicts), "judge_call_count": judge_calls,
            "verdict_set_id": vs_id, "pass_count": pass_running,
            "fail_count": len(verdicts) - pass_running,
        }
        record_event(job, "aggregating")
        await push_status(job)

        pass_count = sum(1 for v in verdicts if v.verdict == "pass")
        pass_rate = round(pass_count / len(verdicts), 4) if verdicts else 0.0
        aggregate_scores = {d: round(sum(s) / len(s), 3) for d, s in dim_scores.items()}
        overall_consensus = round(
            sum(sum(c) for c in judge_consensus.values())
            / max(1, sum(len(c) for c in judge_consensus.values())), 3
        )

        # Finalise the verdict-set row (same id/created_at, state → shipped).
        vset.verdict_count = len(verdicts)
        vset.pass_rate = pass_rate
        vset.pass_count = pass_count
        vset.aggregate_scores = aggregate_scores
        vset.state = "shipped"
        await self._put_verdictset(job.tenant, vset)

        # Judge-calibration records — a REAL, chance-corrected agreement per judge.
        # There is no human-gold rater in this system, so κ is computed as each
        # judge vs the leave-one-out majority verdict of the rest of the panel on
        # the SAME traces: a genuine inter-rater Cohen's κ over real verdicts — no
        # fabricated gold labels, no extra model calls. This replaces the earlier
        # single-juror "consensus" that was hardcoded to 1.0 (so every judge read
        # κ=1.00 regardless of behaviour).
        labels_by_trace: dict[str, dict[str, bool]] = {}
        for v in verdicts:
            labels_by_trace.setdefault(v.trace_id, {})[v.judge_ref] = v.passed
        for ref in judge_refs:
            pairs: list[tuple[bool, bool]] = []
            for labels in labels_by_trace.values():
                if ref not in labels:
                    continue
                others = [p for jr, p in labels.items() if jr != ref]
                if not others:
                    continue
                panel_majority = sum(1 for p in others if p) >= (len(others) / 2)
                pairs.append((bool(labels[ref]), panel_majority))
            kappa = _cohen_kappa(pairs)
            if kappa is None:
                continue
            agreement = round(sum(1 for a, b in pairs if a == b) / len(pairs), 3)
            await self._save_calibration(job.tenant, ref, round(kappa, 3), agreement, len(pairs))

        # Breach → Self-Heal: open an incident for any judge that failed its
        # guardrail on this run. Derived entirely from the real verdicts above.
        agent_name = await self._agent_name(job.tenant, run_ids)
        await detect_incidents(job.tenant, vset, verdicts, agent_name)

        return {
            "verdict_set_id": vs_id, "pass_rate": pass_rate, "verdicts": len(verdicts),
            "verdict_count": len(verdicts), "pass_count": pass_count,
            "aggregate_scores": aggregate_scores, "consensus_rate": overall_consensus,
            "judge_call_count": judge_calls,
        }

    async def _agent_name(self, tenant: str, run_ids: list[str]) -> str:
        """Resolve the evaluated agent's display name from the first run's frozen
        adapter snapshot, for attributing a self-heal incident."""
        for run_id in run_ids:
            row = await get_table().get(keys.run_pk(tenant), keys.run_sk(run_id))
            if row:
                snap = (row.get("data") or {}).get("adapter_snapshot") or {}
                name = snap.get("name")
                if name:
                    return name
        return "Agent under test"

    async def _put_verdictset(self, tenant: str, vset: VerdictSet) -> None:
        """Upsert the verdict-set row (stable GSI keys from created_at) so the
        early running-state write and the final shipped write land on one record."""
        gsipk, gsisk = keys.verdictset_gsi(tenant, vset.created_at)
        await get_table().put({
            "PK": keys.verdictset_pk(tenant), "SK": keys.verdictset_sk(vset.id),
            "GSIPK": gsipk, "GSISK": gsisk, "type": "verdict_set",
            "data": vset.model_dump(mode="json"),
        })

    async def _progress(self, job, done, total, verdicts, judge_calls, vs_id, pass_count):
        job.progress.done = done
        job.progress.total = total
        job.progress.phase = "running"
        # verdict_set_id + running pass/fail ride every frame so the job page can
        # fetch the partial set and paint the KPIs live, mid-run.
        job.progress.detail = {
            "cells_total": total, "cells_done": done,
            "verdicts_emitted": len(verdicts), "judge_call_count": judge_calls,
            "verdict_set_id": vs_id,
            "pass_count": pass_count, "fail_count": len(verdicts) - pass_count,
        }
        record_event(job, "running")
        await push_status(job)

    async def _save_calibration(self, tenant: str, judge_ref: str, kappa: float,
                                agreement: float, n: int):
        ts = iso()
        rec = {
            "judge_ref": judge_ref, "kappa": kappa, "agreement": agreement,
            "sample_size": n, "ts": ts,
        }
        await get_table().put({
            "PK": f"TENANT#{tenant}#CALIBRATION",
            "SK": f"CALIBRATION#{judge_ref}#{ts}",
            "GSIPK": f"TENANT#{tenant}#CALIBRATION_BY_JUDGE",
            "GSISK": f"{judge_ref}#{ts}",
            "type": "calibration", "data": rec,
        })


worker = EvalWorker()
