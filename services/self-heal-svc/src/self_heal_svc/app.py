"""self-heal-svc — closed-loop remediation read API + remediation-ship worker.

Reads (incidents, policies, registry, quality rollup, summary) are sync. The one
async job is remediation-ship, bound in the lifespan and driven from the
orchestrator when a candidate fix is approved.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from eeof_core.context import principal_from_headers
from eeof_core.dataplane import get_bus
from eeof_core.models import IncidentActionRequest, Policy, PolicyDraft, Principal

from .seed import build_policy
from .store import (
    ensure_seeded,
    get_incident,
    get_quality,
    list_actions,
    list_incidents,
    list_policies,
    save_incident,
    save_policy,
    summary,
)
from .worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_bus().connect()
    await worker.start()
    yield


app = FastAPI(title="self-heal-svc", version="0.1.0", lifespan=lifespan)


def principal(request: Request) -> Principal:
    return principal_from_headers(request.headers)


@app.get("/health")
async def health() -> dict:
    return {"service": "self-heal-svc", "status": "ok", "consumes": "heal.jobs"}


@app.get("/self-heal/incidents")
async def incidents(status: str | None = None, p: Principal = Depends(principal)) -> list[dict]:
    return [i.model_dump(mode="json") for i in await list_incidents(p.tenant, status)]


@app.get("/self-heal/incidents/{incident_id}")
async def incident(incident_id: str, p: Principal = Depends(principal)) -> dict:
    inc = await get_incident(p.tenant, incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    return inc.model_dump(mode="json")


@app.post("/self-heal/incidents/{incident_id}/action")
async def incident_action(
    incident_id: str, req: IncidentActionRequest, p: Principal = Depends(principal)
) -> dict:
    """Human-in-the-loop verdict. `ticket`/`reject` mutate synchronously; `approve`
    is acknowledged here and the actual ship runs as the async `self_heal.remediate`
    job submitted by the orchestrator (this endpoint just records intent)."""
    inc = await get_incident(p.tenant, incident_id)
    if not inc:
        raise HTTPException(404, "incident not found")
    if req.action == "ticket":
        inc.status = "escalated"
        inc.dispo = "Routed to ticket · awaiting human"
        inc.dispo_class = "warn"
        await save_incident(p.tenant, inc)
    elif req.action == "reject":
        inc.status = "open"
        inc.stage = "rca"
        inc.dispo = "Fix rejected · RCA re-opened"
        inc.dispo_class = "idle"
        inc.fix = None
        for step in inc.timeline:
            if step.stage in ("simulate", "remediate"):
                step.status = "queued"
            if step.stage == "rca":
                step.status = "active"
        await save_incident(p.tenant, inc)
    return {"incident_id": incident_id, "action": req.action, "status": inc.status}


@app.get("/self-heal/policies")
async def policies(p: Principal = Depends(principal)) -> list[dict]:
    return [pol.model_dump(mode="json") for pol in await list_policies(p.tenant)]


@app.post("/self-heal/policies", status_code=201)
async def create_policy(draft: PolicyDraft, p: Principal = Depends(principal)) -> dict:
    """Author a new governing policy from structured scope. The service derives the
    human trigger + rendered DSL; matching stays structured (dimensions + agent)."""
    name = (draft.name or "").strip()
    if not name:
        raise HTTPException(400, "policy name is required")
    dims = [d.strip() for d in draft.dimensions if d and d.strip()]
    if not dims:
        raise HTTPException(400, "select at least one judge for the policy to govern")
    band = None if draft.always_ticket else draft.band
    if band is not None and not (0.0 <= band <= 1.0):
        raise HTTPException(400, "confidence band must be between 0 and 1")
    await ensure_seeded(p.tenant)
    if any(pol.name == name for pol in await list_policies(p.tenant)):
        raise HTTPException(409, f"a policy named '{name}' already exists")
    policy = Policy.model_validate(build_policy(
        name, dims, (draft.agent or "").strip() or None, band,
        bool(draft.always_ticket), (draft.notify or "").strip(),
    ))
    await save_policy(p.tenant, policy)
    return policy.model_dump(mode="json")


@app.get("/self-heal/registry")
async def registry(p: Principal = Depends(principal)) -> list[dict]:
    return [a.model_dump(mode="json") for a in await list_actions(p.tenant)]


@app.get("/self-heal/playbook")
async def playbook(p: Principal = Depends(principal)) -> dict:
    """Agent-side remediation playbook keyed by judge dimension — the concrete
    code/prompt-level fix behind each registry action category. Static core config."""
    from eeof_core.self_heal_playbook import REMEDIATION_PLAYBOOK

    return REMEDIATION_PLAYBOOK


@app.get("/self-heal/quality")
async def quality(p: Principal = Depends(principal)) -> dict:
    return await get_quality(p.tenant)


@app.get("/self-heal/summary")
async def heal_summary(p: Principal = Depends(principal)) -> dict:
    return (await summary(p.tenant)).model_dump(mode="json")
