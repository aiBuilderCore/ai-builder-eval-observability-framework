"""observability-svc — read API + trace ingest + evidence-pack worker."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from eeof_core.context import principal_from_headers
from eeof_core.dataplane import get_bus
from eeof_core.models import MonitorDraft, Principal

from .store import (
    create_monitor,
    evaluate_gate,
    get_evidence,
    list_batches,
    list_calibration,
    list_evidence,
    list_incidents,
    list_monitors,
)
from .worker import start_ingest, worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_bus().connect()
    await start_ingest()
    await worker.start()
    yield


app = FastAPI(title="observability-svc", version="0.1.0", lifespan=lifespan)


def principal(request: Request) -> Principal:
    return principal_from_headers(request.headers)


@app.get("/health")
async def health() -> dict:
    return {"service": "observability-svc", "status": "ok", "consumes": "trace.events.*, obs.jobs"}


@app.get("/observability/batches")
async def batches(p: Principal = Depends(principal)) -> list[dict]:
    return [b.model_dump(mode="json") for b in await list_batches(p.tenant)]


@app.get("/observability/monitors")
async def monitors(p: Principal = Depends(principal)) -> list[dict]:
    return [m.model_dump(mode="json") for m in await list_monitors(p.tenant)]


@app.post("/observability/monitors", status_code=201)
async def post_monitor(draft: MonitorDraft, p: Principal = Depends(principal)) -> dict:
    return (await create_monitor(p.tenant, draft)).model_dump(mode="json")


@app.get("/observability/incidents")
async def incidents(state: str | None = None, p: Principal = Depends(principal)) -> list[dict]:
    return [i.model_dump(mode="json") for i in await list_incidents(p.tenant, state)]


@app.get("/observability/gate/{candidate}")
async def gate(
    candidate: str, baseline: str | None = None, p: Principal = Depends(principal)
) -> dict:
    return (await evaluate_gate(p.tenant, candidate, baseline=baseline)).model_dump(mode="json")


@app.get("/observability/evidence")
async def evidence_list(p: Principal = Depends(principal)) -> list[dict]:
    return [e.model_dump(mode="json") for e in await list_evidence(p.tenant)]


@app.get("/observability/evidence/{pack_id}")
async def evidence(pack_id: str, p: Principal = Depends(principal)) -> dict:
    pack = await get_evidence(p.tenant, pack_id)
    if not pack:
        raise HTTPException(404, "evidence pack not found")
    return pack.model_dump(mode="json")


@app.get("/observability/calibration")
async def calibration(p: Principal = Depends(principal)) -> list[dict]:
    return await list_calibration(p.tenant)


@app.get("/observability/quality")
async def quality(p: Principal = Depends(principal)) -> dict:
    # Application quality (verdicts by agent) + Quality by pillar (by judge→pillar).
    from eeof_core.rollups import quality_rollup

    return await quality_rollup(p.tenant)


@app.get("/observability/spend")
async def spend(p: Principal = Depends(principal)) -> dict:
    # Per-stage 24h spend, derived from real token totals + record counts.
    from eeof_core.rollups import spend_rollup

    return await spend_rollup(p.tenant)
