"""API Orchestration Service — the only public edge (REST + WebSocket).

Sync commands/queries are proxied to the owning capability service. Heavy work
is accepted synchronously (`202 + job_id`) and queued; progress streams back over
the WebSocket. Auth/tenancy is resolved here and forwarded to internal services.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from eeof_core.context import principal_from_bearer
from eeof_core.dataplane import get_bus, get_table, keys
from eeof_core.ids import new_id
from eeof_core.jobs import get_job, list_jobs
from eeof_core.models import (
    AdapterDraft,
    EvidenceRequest,
    IncidentActionRequest,
    JudgeDraft,
    JuryDraft,
    MonitorDraft,
    PersonaDraft,
    PersonaRef,
    Principal,
    RunRequest,
    SeedSet,
)

from .clients import proxy
from .submit import submit_job


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_bus().connect()
    yield


app = FastAPI(title="api-orchestration", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
api = APIRouter(prefix="/api/v1")


def principal(authorization: str | None = Header(default=None)) -> Principal:
    return principal_from_bearer(authorization)


# ----------------------------------------------------------------------------
# Personas (sync) -> persona-svc
# ----------------------------------------------------------------------------
@api.get("/personas")
async def list_personas(p: Principal = Depends(principal)):
    return await proxy("persona", "GET", "/personas", p)


@api.post("/personas", status_code=201)
async def create_persona(draft: PersonaDraft, p: Principal = Depends(principal)):
    return await proxy("persona", "POST", "/personas", p, json=draft.model_dump())


@api.get("/personas/{persona_id}")
async def get_persona(persona_id: str, version: str | None = None, p: Principal = Depends(principal)):
    return await proxy(
        "persona", "GET", f"/personas/{persona_id}", p,
        params={"version": version} if version else None,
    )


@api.put("/personas/{persona_id}")
async def update_persona(
    persona_id: str, draft: PersonaDraft, level: str = "minor", p: Principal = Depends(principal)
):
    return await proxy(
        "persona", "PUT", f"/personas/{persona_id}", p,
        json=draft.model_dump(), params={"level": level},
    )


@api.delete("/personas/{persona_id}", status_code=204)
async def delete_persona(persona_id: str, p: Principal = Depends(principal)):
    await proxy("persona", "DELETE", f"/personas/{persona_id}", p)


# ----------------------------------------------------------------------------
# Question Generation (async) -> qgen.jobs
# ----------------------------------------------------------------------------
class QuestionSetRequest(BaseModel):
    persona_refs: list[PersonaRef]
    intents: list[str] = Field(default_factory=lambda: ["helpfulness"])
    strategy: str = "rainbow"
    scenarios: list[str] = Field(default_factory=lambda: ["short.chat.easy"])
    shapes: list[str] = Field(default_factory=lambda: ["ambiguate", "adversify"])
    count_per_persona: int = 8


@api.post("/question-sets", status_code=202)
async def create_question_set(
    req: QuestionSetRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    p: Principal = Depends(principal),
):
    # Freeze the full persona snapshots at submit time.
    snapshots = []
    for ref in req.persona_refs:
        persona = await proxy(
            "persona", "GET", f"/personas/{ref.id}", p,
            params={"version": ref.version} if ref.version else None,
        )
        snapshots.append(persona)
    inputs = {
        "persona_snapshots": snapshots,
        "intents": req.intents,
        "strategy": req.strategy,
        "scenarios": req.scenarios,
        "shapes": req.shapes,
        "count_per_persona": req.count_per_persona,
    }
    return await submit_job(
        p, kind="qgen.generate", stage="qgen", inputs=inputs, idempotency_key=idempotency_key
    )


@api.get("/question-sets")
async def list_question_sets(p: Principal = Depends(principal)):
    gsipk, _ = keys.seedset_gsi(p.tenant, "")
    rows = await get_table().query_gsi(gsipk)
    return [r["data"] for r in rows]


@api.get("/question-sets/{seed_set_id}")
async def get_question_set(seed_set_id: str, p: Principal = Depends(principal)):
    row = await get_table().get(keys.seedset_pk(p.tenant), keys.seedset_sk(seed_set_id))
    if not row:
        raise HTTPException(404, "seed set not found")
    return SeedSet.model_validate(row["data"]).model_dump(mode="json")


@api.get("/question-sets/{seed_set_id}/questions")
async def get_question_set_questions(seed_set_id: str, p: Principal = Depends(principal)):
    rows = await get_table().query(keys.question_pk(seed_set_id), "QUESTION#")
    return [r["data"] for r in rows]


# ----------------------------------------------------------------------------
# Adapters (sync) + Simulation runs (async)
# ----------------------------------------------------------------------------
@api.get("/adapters")
async def list_adapters(p: Principal = Depends(principal)):
    return await proxy("simulation", "GET", "/adapters", p)


@api.post("/adapters", status_code=201)
async def create_adapter(draft: AdapterDraft, p: Principal = Depends(principal)):
    return await proxy("simulation", "POST", "/adapters", p, json=draft.model_dump())


@api.post("/simulation/runs", status_code=202)
async def create_run(
    req: RunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    p: Principal = Depends(principal),
):
    adapters = await proxy("simulation", "GET", "/adapters", p)
    snapshot = next((a for a in adapters if a["id"] == req.adapter_id), None)
    if snapshot is None:
        raise HTTPException(400, f"adapter {req.adapter_id} not found")
    run_id = new_id("run")
    inputs = {
        "run_id": run_id,
        "seed_set_id": req.seed_set_id,
        "adapter_snapshot": snapshot,
        "mode": req.mode,
        "max_turns": req.max_turns,
        "concurrency": req.concurrency,
        "user_simulator_model": req.user_simulator_model,
    }
    return await submit_job(
        p, kind="simulation.run", stage="sim", inputs=inputs,
        idempotency_key=idempotency_key, extra_result={"run_id": run_id},
    )


@api.get("/simulation/runs")
async def list_runs(p: Principal = Depends(principal)):
    gsipk, _ = keys.run_gsi(p.tenant, "", "")
    rows = await get_table().query_gsi(gsipk)
    return [r["data"] for r in rows]


@api.get("/simulation/runs/{run_id}")
async def get_run(run_id: str, p: Principal = Depends(principal)):
    return await proxy("simulation", "GET", f"/simulation/runs/{run_id}", p)


@api.get("/simulation/runs/{run_id}/traces")
async def get_run_traces(run_id: str, p: Principal = Depends(principal)):
    return await proxy("simulation", "GET", f"/simulation/runs/{run_id}/traces", p)


@api.get("/simulation/traces/{trace_id}")
async def get_trace(trace_id: str, p: Principal = Depends(principal)):
    return await proxy("simulation", "GET", f"/simulation/traces/{trace_id}", p)


# ----------------------------------------------------------------------------
# Judges/Juries (sync) + Evaluation (async)
# ----------------------------------------------------------------------------
@api.get("/judges")
async def list_judges(p: Principal = Depends(principal)):
    return await proxy("judge-registry", "GET", "/judges", p)


@api.post("/judges", status_code=201)
async def create_judge(draft: JudgeDraft, p: Principal = Depends(principal)):
    return await proxy("judge-registry", "POST", "/judges", p, json=draft.model_dump())


@api.post("/juries", status_code=201)
async def create_jury(draft: JuryDraft, p: Principal = Depends(principal)):
    return await proxy("judge-registry", "POST", "/juries", p, json=draft.model_dump())


class EvalSubmit(BaseModel):
    run_ids: list[str]
    judge_refs: list[str] = Field(default_factory=list)
    panel_id: str | None = None
    mode: str = "panel"
    aggregation: str = "majority"
    mitigations: list[str] = Field(default_factory=list)


@api.post("/evaluation/jobs", status_code=202)
async def create_eval(
    req: EvalSubmit,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    p: Principal = Depends(principal),
):
    judges = await proxy("judge-registry", "GET", "/judges", p)  # ensures builtins exist
    latest = {}
    for j in judges:
        cur = latest.get(j["name"])
        if cur is None or j["version"] > cur["version"]:
            latest[j["name"]] = j
    if req.judge_refs:
        refs = req.judge_refs
    else:
        refs = [f"{n}@v{latest[n]['version']}" for n in ["helpfulness"] if n in latest] or ["helpfulness@v1"]
    rubrics = {}
    for ref in refs:
        name = ref.split("@")[0]
        rubrics[ref] = latest.get(name, {}).get("rubric", name)
    inputs = {
        "run_ids": req.run_ids,
        "judge_refs": refs,
        "judge_rubrics": rubrics,
        "aggregation": req.aggregation,
    }
    return await submit_job(
        p, kind="evaluation.score", stage="eval", inputs=inputs, idempotency_key=idempotency_key
    )


@api.get("/verdict-sets")
async def list_verdict_sets(p: Principal = Depends(principal)):
    gsipk, _ = keys.verdictset_gsi(p.tenant, "")
    rows = await get_table().query_gsi(gsipk)
    return [r["data"] for r in rows]


@api.get("/verdict-sets/{vs_id}")
async def get_verdict_set(vs_id: str, p: Principal = Depends(principal)):
    return await proxy("evaluation", "GET", f"/verdict-sets/{vs_id}", p)


@api.get("/runs/{run_id}/verdicts")
async def get_run_verdicts(run_id: str, p: Principal = Depends(principal)):
    return await proxy("evaluation", "GET", f"/runs/{run_id}/verdicts", p)


# ----------------------------------------------------------------------------
# Observability
# ----------------------------------------------------------------------------
@api.get("/observability/batches")
async def obs_batches(p: Principal = Depends(principal)):
    return await proxy("observability", "GET", "/observability/batches", p)


@api.get("/observability/monitors")
async def obs_monitors(p: Principal = Depends(principal)):
    return await proxy("observability", "GET", "/observability/monitors", p)


@api.post("/observability/monitors", status_code=201)
async def obs_create_monitor(draft: MonitorDraft, p: Principal = Depends(principal)):
    return await proxy("observability", "POST", "/observability/monitors", p, json=draft.model_dump())


@api.get("/observability/incidents")
async def obs_incidents(state: str | None = None, p: Principal = Depends(principal)):
    return await proxy(
        "observability", "GET", "/observability/incidents", p,
        params={"state": state} if state else None,
    )


@api.get("/observability/gate/{candidate}")
async def obs_gate(candidate: str, p: Principal = Depends(principal)):
    return await proxy("observability", "GET", f"/observability/gate/{candidate}", p)


@api.post("/observability/evidence", status_code=202)
async def obs_evidence(
    req: EvidenceRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    p: Principal = Depends(principal),
):
    return await submit_job(
        p, kind="observability.evidence", stage="obs",
        inputs=req.model_dump(), idempotency_key=idempotency_key,
    )


@api.get("/observability/evidence")
async def obs_list_evidence(p: Principal = Depends(principal)):
    return await proxy("observability", "GET", "/observability/evidence", p)


@api.get("/observability/evidence/{pack_id}")
async def obs_get_evidence(pack_id: str, p: Principal = Depends(principal)):
    return await proxy("observability", "GET", f"/observability/evidence/{pack_id}", p)


@api.get("/observability/calibration")
async def obs_calibration(p: Principal = Depends(principal)):
    return await proxy("observability", "GET", "/observability/calibration", p)


@api.get("/observability/quality")
async def obs_quality(p: Principal = Depends(principal)):
    # Application quality + Quality by pillar, aggregated from real verdicts.
    return await proxy("observability", "GET", "/observability/quality", p)


@api.get("/observability/spend")
async def obs_spend(p: Principal = Depends(principal)):
    # Per-stage 24h spend, derived from real token totals + record counts.
    return await proxy("observability", "GET", "/observability/spend", p)


# ----------------------------------------------------------------------------
# Self-Heal — closed-loop remediation (reads sync; approve → async ship job)
# ----------------------------------------------------------------------------
@api.get("/self-heal/incidents")
async def heal_incidents(status: str | None = None, p: Principal = Depends(principal)):
    return await proxy(
        "self-heal", "GET", "/self-heal/incidents", p,
        params={"status": status} if status else None,
    )


@api.get("/self-heal/incidents/{incident_id}")
async def heal_incident(incident_id: str, p: Principal = Depends(principal)):
    return await proxy("self-heal", "GET", f"/self-heal/incidents/{incident_id}", p)


@api.post("/self-heal/incidents/{incident_id}/action")
async def heal_incident_action(
    incident_id: str,
    req: IncidentActionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    p: Principal = Depends(principal),
):
    # Approving a candidate ships it — the visible loop-closing step runs as the
    # async self_heal.remediate job so progress streams over the WebSocket.
    if req.action == "approve":
        return await submit_job(
            p, kind="self_heal.remediate", stage="heal",
            inputs={"incident_id": incident_id, "action": req.action},
            idempotency_key=idempotency_key, extra_result={"incident_id": incident_id},
        )
    # ticket / reject mutate synchronously in the service.
    return await proxy(
        "self-heal", "POST", f"/self-heal/incidents/{incident_id}/action", p,
        json=req.model_dump(),
    )


@api.get("/self-heal/policies")
async def heal_policies(p: Principal = Depends(principal)):
    return await proxy("self-heal", "GET", "/self-heal/policies", p)


@api.get("/self-heal/registry")
async def heal_registry(p: Principal = Depends(principal)):
    return await proxy("self-heal", "GET", "/self-heal/registry", p)


@api.get("/self-heal/quality")
async def heal_quality(p: Principal = Depends(principal)):
    return await proxy("self-heal", "GET", "/self-heal/quality", p)


@api.get("/self-heal/summary")
async def heal_summary(p: Principal = Depends(principal)):
    return await proxy("self-heal", "GET", "/self-heal/summary", p)


# ----------------------------------------------------------------------------
# Jobs (uniform lifecycle)
# ----------------------------------------------------------------------------
@api.get("/jobs/{job_id}")
async def get_job_ep(job_id: str, p: Principal = Depends(principal)):
    job = await get_job(p.tenant, job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job.model_dump(mode="json")


@api.get("/jobs")
async def list_jobs_ep(state: str | None = None, p: Principal = Depends(principal)):
    return [j.model_dump(mode="json") for j in await list_jobs(p.tenant, state)]


app.include_router(api)


@app.get("/health")
async def health() -> dict:
    return {"service": "api-orchestration", "status": "ok"}


# ----------------------------------------------------------------------------
# WebSocket gateway — one socket per session; subscribe to job ids.
# ----------------------------------------------------------------------------
@app.websocket("/api/v1/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    watched: set[str] = set()
    bus = get_bus()

    async def on_status(msg: dict) -> None:
        if msg.get("job_id") in watched:
            try:
                await sock.send_json(msg)
            except RuntimeError:
                pass

    unsub = await bus.subscribe("status.>", on_status)
    try:
        while True:
            msg = await sock.receive_json()
            kind = msg.get("type")
            job_id = msg.get("job_id")
            if kind == "subscribe" and job_id:
                watched.add(job_id)
                snapshot = await bus.kv_get("job_progress", job_id)
                if snapshot:
                    await sock.send_json(snapshot)
            elif kind == "unsubscribe" and job_id:
                watched.discard(job_id)
    except WebSocketDisconnect:
        pass
    finally:
        unsub()


# Serve the SPA at "/" (single origin with the API) when present.
# Mounted last so /api/v1/* and /health keep precedence. No-cache headers keep
# the browser from serving a stale bundle during active development.
import os  # noqa: E402

from starlette.staticfiles import StaticFiles  # noqa: E402


class NoCacheStatic(StaticFiles):
    def is_not_modified(self, response_headers, request_headers) -> bool:  # noqa: ARG002
        return False

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp


_frontend = os.environ.get("FRONTEND_DIR") or os.path.join(os.getcwd(), "frontend-web")
if os.path.isdir(_frontend):
    app.mount("/", NoCacheStatic(directory=_frontend, html=True), name="frontend")
