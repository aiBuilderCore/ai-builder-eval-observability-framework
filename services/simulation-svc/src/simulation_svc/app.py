"""simulation-svc — async run worker + sync adapter registration + run reads."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from eeof_core.context import principal_from_headers
from eeof_core.dataplane import get_blob, get_bus, get_table, keys
from eeof_core.models import Adapter, AdapterDraft, Principal, Run

from .adapters import ensure_builtin_adapters, list_adapters, register_adapter
from .worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_bus().connect()
    await worker.start()
    yield


app = FastAPI(title="simulation-svc", version="0.1.0", lifespan=lifespan)


def principal(request: Request) -> Principal:
    return principal_from_headers(request.headers)


@app.get("/health")
async def health() -> dict:
    return {"service": "simulation-svc", "status": "ok", "consumes": worker.subject}


# --- Adapters (sync) ---
@app.get("/adapters")
async def get_adapters(p: Principal = Depends(principal)) -> list[dict]:
    await ensure_builtin_adapters(p.tenant)
    return [a.model_dump(mode="json") for a in await list_adapters(p.tenant)]


@app.post("/adapters", status_code=201)
async def post_adapter(draft: AdapterDraft, p: Principal = Depends(principal)) -> dict:
    adapter: Adapter = await register_adapter(p.tenant, draft)
    return adapter.model_dump(mode="json")


# --- Run reads ---
@app.get("/simulation/runs/{run_id}")
async def get_run(run_id: str, p: Principal = Depends(principal)) -> dict:
    row = await get_table().get(keys.run_pk(p.tenant), keys.run_sk(run_id))
    if not row:
        raise HTTPException(404, "run not found")
    return Run.model_validate(row["data"]).model_dump(mode="json")


@app.get("/simulation/runs/{run_id}/traces")
async def get_run_traces(run_id: str, p: Principal = Depends(principal)) -> list[dict]:
    rows = await get_table().query(keys.trace_pk(run_id), "TRACE#")
    return [r["data"] for r in rows]


@app.get("/simulation/traces/{trace_id}")
async def get_trace(trace_id: str, p: Principal = Depends(principal)) -> dict:
    rows = await get_table().query_gsi(f"TRACE#{trace_id}")
    if not rows:
        raise HTTPException(404, "trace not found")
    return await get_blob().get_json(rows[0]["blob_uri"])
