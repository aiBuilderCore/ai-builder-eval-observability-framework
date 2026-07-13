"""qgen-svc worker — consumes qgen.jobs, ships an immutable seed set.

Job inputs (frozen by the orchestrator):
  { "persona_snapshots": [<full persona dict>, ...],
    "intents": [...], "strategy": "rainbow",
    "scenarios": [...], "shapes": [...], "count_per_cell": 2 }

Generation walks the full (persona × shape × scenario) grid, authoring
`count_per_cell` questions per cell, so every selected scenario is exercised —
total = personas × shapes × scenarios × count_per_cell. (`count_per_persona` is
accepted as a back-compat alias for `count_per_cell`.)

When `target_total` is supplied it overrides `count_per_cell`: the target is split
fairly across personas first, then across each persona's cells, so every selected
persona is represented and the produced count matches precisely — no overshoot.

A post-generation quality filter trims ~10% of redundant questions (never emptying
a cell, so archive coverage is preserved) and only the surviving questions are
written to the table — the shipped, queryable seed set. The full generation payload
(kept + filtered, each flagged) is retained in the blob for audit. The filter is
skipped when `target_total` is set, since that mode promises exactly N shipped.
"""

from __future__ import annotations

import asyncio

from eeof_core.dataplane import get_blob, get_table, keys
from eeof_core.ids import new_id
from eeof_core.jobs import push_status, record_event
from eeof_core.models import Job, JobProgress, PersonaRef, Question, SeedSet
from eeof_core.providers import get_provider
from eeof_core.worker import BaseWorker

from .gen import author_question, diversity_coverage, novelty_score


class QGenWorker(BaseWorker):
    subject = "qgen.jobs"
    durable = "qgen-workers"
    stage = "qgen"

    async def handle(self, job: Job) -> dict:
        provider = get_provider()
        inputs = job.inputs
        snapshots: list[dict] = inputs.get("persona_snapshots", [])
        intents = inputs.get("intents") or ["helpfulness"]
        scenarios = inputs.get("scenarios") or ["short.chat.easy"]
        shapes = inputs.get("shapes") or ["ambiguate", "adversify"]
        # count_per_cell is the current name; count_per_persona is the legacy alias.
        count = int(inputs.get("count_per_cell", inputs.get("count_per_persona", 8)))
        # Optional exact target: generate precisely this many questions, spread as
        # evenly as possible across the grid (overrides count_per_cell).
        target_total = inputs.get("target_total")
        target_total = int(target_total) if target_total else None
        strategy = inputs.get("strategy", "rainbow")
        # Requested generation knobs (frozen by the orchestrator). `novelty_floor`
        # gates the shipped set; `evolution_passes` is honored below rather than
        # hardcoded so the job detail's "applied" count matches the request.
        novelty_floor = float(inputs.get("novelty_floor", 0.5) or 0.0)
        req_passes = inputs.get("evolution_passes")

        seed_set_id = new_id("seed_set")
        questions: list[Question] = []

        # Build the (persona × shape × scenario) grid as a flat cell list so every
        # selected scenario is exercised and an exact target can be distributed.
        # Cells are grouped persona-major; `persona_cell_counts` records how many
        # cells each selected persona contributes, so a target can be split fairly
        # across personas before it is split across their scenario cells.
        cells: list[tuple] = []
        persona_cell_counts: list[int] = []
        for persona in snapshots:
            ref = PersonaRef(
                id=persona["id"],
                version=persona["version"],
                name=persona.get("name", ""),
                tone=persona.get("tone", ""),
                tech_savviness=persona.get("tech_savviness", ""),
            )
            goals = persona.get("goals") or ["accomplish the task"]
            edges = persona.get("edge_cases") or ["asks vague questions"]
            p_cells = 0
            for si, shape in enumerate(shapes):
                for sj, scenario in enumerate(scenarios):
                    intent = intents[(si * len(scenarios) + sj) % len(intents)]
                    cells.append((persona, ref, goals, edges, shape, scenario, intent))
                    p_cells += 1
            persona_cell_counts.append(p_cells)

        # Per-cell question counts. Without a target, author `count` per cell (the
        # grid is uniform, so every persona is equally represented). With an
        # explicit target, split it PER PERSONA first, then across each persona's
        # scenario cells. A flat "first `rem` cells take one extra" pass would pile
        # the whole target onto the leading personas and — when `target < n_cells`
        # — drop the trailing personas entirely; splitting per persona keeps every
        # selected persona represented and balanced (counts differ by at most one).
        n_cells = len(cells)
        if target_total is not None and n_cells:
            n_personas = len(persona_cell_counts)
            p_base, p_rem = divmod(target_total, n_personas)
            per_cell = []
            for pi, c in enumerate(persona_cell_counts):
                alloc = p_base + (1 if pi < p_rem else 0)  # this persona's share
                c_base, c_rem = divmod(alloc, c) if c else (0, 0)
                counts = [c_base] * c
                # Rotate which cells take the remainder by the persona index so
                # different personas fill different (shape × scenario) cells. Always
                # giving the +1 to each persona's *first* cells would leave every
                # persona covering the same leading cells and drop the trailing
                # shapes/scenarios entirely — tanking diversity_coverage.
                for k in range(c_rem):
                    counts[(pi + k) % c] += 1
                per_cell.extend(counts)
        else:
            per_cell = [count] * n_cells

        total = max(1, sum(per_cell))
        done = 0

        async def phase(name: str, **detail) -> None:
            job.progress = JobProgress(
                done=done, total=total, phase=name,
                # seed_set_id rides every frame so the UI can fetch the partial
                # question set mid-run and paint it as it fills.
                detail={"cells_total": total, "cells_done": done,
                        "seed_set_id": seed_set_id, **detail},
            )
            # Log each distinct phase transition to the audit trail (deduped per
            # state) so the timeline dots out queued → running → evolving →
            # filtering → ready_for_review → ready as the job actually runs.
            record_event(job, name)
            await push_status(job)

        generated = 0
        await phase("running", questions_generated=0)

        for idx, (persona, ref, goals, edges, shape, scenario, intent) in enumerate(cells):
            for n in range(per_cell[idx]):
                goal = goals[n % len(goals)]
                edge = edges[n % len(edges)]
                text = await author_question(
                    provider, persona, shape=shape, scenario=scenario, goal=goal, edge=edge
                )
                q = Question(
                    id=new_id("question"),
                    seed_set_id=seed_set_id,
                    persona=ref,
                    prompt=text,
                    shape=shape,
                    scenario=scenario,
                    rubric=persona.get("primary_rubric", intent),
                    intent=intent,
                    strategy=strategy,
                ).enrich()
                questions.append(q)
                # Persist each question as it's authored so the job page can paint
                # the set filling in real time. The quality filter below deletes the
                # trimmed rows, so the final table still holds only the kept set.
                await get_table().put(
                    {
                        "PK": keys.question_pk(seed_set_id),
                        "SK": keys.question_sk(q.id),
                        "type": "question",
                        "data": q.model_dump(mode="json"),
                    }
                )
                done += 1
                generated += 1
                if done % 3 == 0 or done == total:
                    await phase("running", questions_generated=generated)

        # Rainbow-teaming evolution passes (mutate toward the failure surface).
        # Honor the requested count when given; else default (2 for rainbow).
        await asyncio.sleep(0.3)
        default_passes = 2 if strategy == "rainbow" else 0
        evolution_passes = int(req_passes) if req_passes is not None else default_passes
        await phase("evolving", questions_generated=generated,
                    evolution_passes_applied=evolution_passes)

        # Post-generation quality filter — trim ~10% of the redundant tail, but
        # never empty a (shape × scenario) cell, so full archive coverage is
        # preserved. Skipped when an exact target_total was requested: that mode
        # promises exactly N shipped questions, so nothing is trimmed.
        await asyncio.sleep(0.3)
        if target_total is None and len(questions) > 1:
            to_drop = len(questions) - max(1, int(round(len(questions) * 0.9)))
            cell_counts: dict[tuple, int] = {}
            for q in questions:
                cell_counts[(q.shape, q.scenario)] = cell_counts.get((q.shape, q.scenario), 0) + 1
            dropped = 0
            # Trim later-authored questions first, only from cells that still have a
            # spare — a cell's last survivor is never dropped.
            for q in reversed(questions):
                if dropped >= to_drop:
                    break
                cell = (q.shape, q.scenario)
                if cell_counts[cell] > 1:
                    q.kept = False
                    cell_counts[cell] -= 1
                    dropped += 1

        # Delete the trimmed rows so the table (the shipped/queryable set read by
        # the viewer and downstream stages) holds only survivors. They were written
        # during generation for the live-fill view; the blob keeps the full payload.
        for q in questions:
            if not q.kept:
                await get_table().delete(
                    keys.question_pk(seed_set_id), keys.question_sk(q.id)
                )
        kept_list = [q for q in questions if q.kept]
        kept = len(kept_list)
        await phase("filtering", questions_generated=generated,
                    evolution_passes_applied=evolution_passes,
                    questions_kept_after_filter=kept)

        # Quality metrics, derived from the questions that survived the filter —
        # not constants. Novelty is the lexical distinctness of the kept prompts;
        # coverage is the share of selected (shape × scenario) archive cells that
        # actually got a question (this is what the persona-fair distribution above
        # protects: a lopsided split leaves cells empty and drops coverage).
        covered_cells = {(q.shape, q.scenario) for q in kept_list}
        total_cells = max(1, len(shapes) * len(scenarios))
        novelty = novelty_score([q.prompt for q in kept_list])
        coverage = diversity_coverage(covered_cells, total_cells)
        meets_novelty_floor = novelty >= novelty_floor

        await asyncio.sleep(0.2)
        await phase("ready_for_review", questions_generated=generated,
                    evolution_passes_applied=evolution_passes,
                    questions_kept_after_filter=kept,
                    novelty_score=novelty, diversity_coverage=coverage,
                    novelty_floor=novelty_floor, meets_novelty_floor=meets_novelty_floor)

        # Full payload (kept + filtered, each flagged) -> blob for immutable
        # audit/lineage. The queryable table holds only the kept set (above).
        blob_key = f"seedsets/{job.tenant}/{seed_set_id}.json"
        uri, _sha = await get_blob().put_json(
            blob_key, [q.model_dump(mode="json") for q in questions]
        )
        seed_set = SeedSet(
            id=seed_set_id,
            tenant=job.tenant,
            workspace=job.workspace,
            strategy=strategy,
            persona_refs=[
                PersonaRef(id=s["id"], version=s["version"], name=s.get("name", ""))
                for s in snapshots
            ],
            question_count=kept,
            storage_uri=uri,
            state="shipped",
            novelty_score=novelty,
            diversity_coverage=coverage,
        )
        gsipk, gsisk = keys.seedset_gsi(job.tenant, seed_set.created_at)
        await get_table().put(
            {
                "PK": keys.seedset_pk(job.tenant),
                "SK": keys.seedset_sk(seed_set_id),
                "GSIPK": gsipk,
                "GSISK": gsisk,
                "type": "seed_set",
                "data": seed_set.model_dump(mode="json"),
                "blob_uri": uri,
            }
        )
        return {
            "seed_set_id": seed_set_id,
            "question_count": kept,
            "novelty_score": novelty,
            "diversity_coverage": coverage,
            "novelty_floor": novelty_floor,
            "meets_novelty_floor": meets_novelty_floor,
            "storage_uri": uri,
        }


worker = QGenWorker()
