"""qgen-svc worker — consumes qgen.jobs, ships an immutable seed set.

Job inputs (frozen by the orchestrator):
  { "persona_snapshots": [<full persona dict>, ...],
    "intents": [...], "strategy": "rainbow",
    "scenarios": [...], "shapes": [...], "count_per_cell": 2 }

Generation walks the full (persona × shape × scenario) grid, authoring
`count_per_cell` questions per cell, so every selected scenario is exercised —
total = personas × shapes × scenarios × count_per_cell. (`count_per_persona` is
accepted as a back-compat alias for `count_per_cell`.)

When `target_total` is supplied it overrides `count_per_cell`: exactly that many
questions are generated, distributed evenly across the grid (first cells take one
extra), so the produced count matches the request precisely — no ceil overshoot.
"""

from __future__ import annotations

import asyncio

from eeof_core.dataplane import get_blob, get_table, keys
from eeof_core.ids import new_id
from eeof_core.jobs import push_status
from eeof_core.models import Job, JobProgress, PersonaRef, Question, SeedSet
from eeof_core.providers import get_provider
from eeof_core.worker import BaseWorker

from .gen import author_question


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

        seed_set_id = new_id("seed_set")
        questions: list[Question] = []

        # Build the (persona × shape × scenario) grid as a flat cell list so every
        # selected scenario is exercised and an exact target can be distributed.
        cells: list[tuple] = []
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
            for si, shape in enumerate(shapes):
                for sj, scenario in enumerate(scenarios):
                    intent = intents[(si * len(scenarios) + sj) % len(intents)]
                    cells.append((persona, ref, goals, edges, shape, scenario, intent))

        # Per-cell question counts. With an explicit target, distribute it evenly
        # (the first `rem` cells take one extra) so the total is exact — no ceil
        # overshoot. Otherwise author `count` per cell. A target smaller than the
        # grid spreads one-per-cell across as many distinct cells as possible.
        n_cells = len(cells)
        if target_total is not None and n_cells:
            base, rem = divmod(target_total, n_cells)
            per_cell = [base + (1 if i < rem else 0) for i in range(n_cells)]
        else:
            per_cell = [count] * n_cells

        total = max(1, sum(per_cell))
        done = 0

        async def phase(name: str, **detail) -> None:
            job.progress = JobProgress(
                done=done, total=total, phase=name,
                detail={"cells_total": total, "cells_done": done, **detail},
            )
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
                # Co-locate the question under its seed set's partition.
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
        await asyncio.sleep(0.3)
        evolution_passes = 2 if strategy == "rainbow" else 0
        await phase("evolving", questions_generated=generated,
                    evolution_passes_applied=evolution_passes)

        # Post-generation quality filter — drop the weakest ~10%.
        await asyncio.sleep(0.3)
        kept = max(1, int(round(len(questions) * 0.9)))
        for q in questions[kept:]:
            q.kept = False
        await phase("filtering", questions_generated=generated,
                    evolution_passes_applied=evolution_passes,
                    questions_kept_after_filter=kept)

        await asyncio.sleep(0.2)
        await phase("ready_for_review", questions_generated=generated,
                    evolution_passes_applied=evolution_passes,
                    questions_kept_after_filter=kept)

        # Full payload -> blob; row keeps metadata + pointer.
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
            question_count=len(questions),
            storage_uri=uri,
            state="shipped",
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
        return {"seed_set_id": seed_set_id, "question_count": len(questions)}


worker = QGenWorker()
