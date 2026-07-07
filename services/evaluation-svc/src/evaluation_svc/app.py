"""evaluation-svc — async scoring worker + sync judge/jury registry + verdict reads."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from eeof_core.context import principal_from_headers
from eeof_core.dataplane import get_bus, get_table, keys
from eeof_core.models import JudgeDraft, JuryDraft, Principal, Verdict, VerdictSet

from .judges import create_judge, create_jury, ensure_builtin_judges, list_judges
from .worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_bus().connect()
    await worker.start()
    yield


app = FastAPI(title="evaluation-svc", version="0.1.0", lifespan=lifespan)


def principal(request: Request) -> Principal:
    return principal_from_headers(request.headers)


@app.get("/health")
async def health() -> dict:
    return {"service": "evaluation-svc", "status": "ok", "consumes": worker.subject}


# --- Judge registry (sync) ---
@app.get("/judges")
async def get_judges(p: Principal = Depends(principal)) -> list[dict]:
    await ensure_builtin_judges(p.tenant)
    return [j.model_dump(mode="json") for j in await list_judges(p.tenant)]


@app.post("/judges", status_code=201)
async def post_judge(draft: JudgeDraft, p: Principal = Depends(principal)) -> dict:
    return (await create_judge(p.tenant, draft)).model_dump(mode="json")


@app.post("/juries", status_code=201)
async def post_jury(draft: JuryDraft, p: Principal = Depends(principal)) -> dict:
    return (await create_jury(p.tenant, draft)).model_dump(mode="json")


# --- Verdict reads ---
@app.get("/verdict-sets/{vs_id}")
async def get_verdict_set(vs_id: str, p: Principal = Depends(principal)) -> dict:
    row = await get_table().get(keys.verdictset_pk(p.tenant), keys.verdictset_sk(vs_id))
    if not row:
        raise HTTPException(404, "verdict set not found")
    vset = VerdictSet.model_validate(row["data"])
    verdicts = await get_table().query(keys.verdict_pk(vs_id), "VERDICT#")
    out = vset.model_dump(mode="json")
    out["verdicts"] = [v["data"] for v in verdicts]
    return out


@app.get("/runs/{run_id}/verdicts")
async def get_run_verdicts(run_id: str, p: Principal = Depends(principal)) -> list[dict]:
    rows = await get_table().query_gsi(f"RUN#{run_id}", "VERDICT#")
    return [Verdict.model_validate(r["data"]).model_dump(mode="json") for r in rows]
