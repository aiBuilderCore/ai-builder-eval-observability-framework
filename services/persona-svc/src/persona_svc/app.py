"""persona-svc — the pipeline's one purely-sync stage.

CRUD + versioning of synthetic personas. Personas are immutable per
(persona_id, version); an edit writes a new version row. Reachable only through
the orchestrator, which forwards the resolved tenant/workspace as headers.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request

from eeof_core.context import principal_from_headers
from eeof_core.dataplane import get_table, keys
from eeof_core.ids import new_id
from eeof_core.models import Persona, PersonaDraft, Principal, bump, iso, slug

app = FastAPI(title="persona-svc", version="0.1.0")


def principal(request: Request) -> Principal:
    return principal_from_headers(request.headers)


async def _store(tenant: str, p: Persona) -> None:
    gsipk, gsisk = keys.persona_gsi(tenant, p.created_at)
    await get_table().put(
        {
            "PK": keys.persona_pk(tenant),
            "SK": keys.persona_sk(p.id, p.version),
            "GSIPK": gsipk,
            "GSISK": gsisk,
            "type": "persona",
            "data": p.model_dump(mode="json"),
        }
    )


def _semver_key(v: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return (a, b, c)


async def _versions(tenant: str, persona_id: str) -> list[Persona]:
    rows = await get_table().query(keys.persona_pk(tenant), f"PERSONA#{persona_id}#")
    return sorted((Persona.model_validate(r["data"]) for r in rows), key=lambda p: _semver_key(p.version))


@app.get("/health")
async def health() -> dict:
    return {"service": "persona-svc", "status": "ok"}


@app.get("/personas")
async def list_personas(p: Principal = Depends(principal)) -> list[dict]:
    gsipk, _ = keys.persona_gsi(p.tenant, "")
    rows = await get_table().query_gsi(gsipk)
    personas = [Persona.model_validate(r["data"]) for r in rows]
    # newest-first, latest version per id
    latest: dict[str, Persona] = {}
    for persona in personas:
        if persona.archived:
            continue
        cur = latest.get(persona.id)
        if cur is None or _semver_key(persona.version) > _semver_key(cur.version):
            latest[persona.id] = persona
    out = sorted(latest.values(), key=lambda x: x.created_at, reverse=True)
    return [x.model_dump(mode="json") for x in out]


@app.post("/personas", status_code=201)
async def create_persona(draft: PersonaDraft, p: Principal = Depends(principal)) -> dict:
    persona_id = f"persona_{slug(draft.name)}"
    # id-collision disambiguation
    existing = await _versions(p.tenant, persona_id)
    if existing:
        persona_id = f"{persona_id}_{new_id('persona').split('_', 1)[1][:6].lower()}"
    persona = Persona(id=persona_id, created_by=p.subject, **draft.model_dump())
    await _store(p.tenant, persona)
    return persona.model_dump(mode="json")


@app.get("/personas/{persona_id}")
async def get_persona(
    persona_id: str, version: str | None = None, p: Principal = Depends(principal)
) -> dict:
    versions = await _versions(p.tenant, persona_id)
    if not versions:
        raise HTTPException(404, "persona not found")
    if version:
        match = next((v for v in versions if v.version == version), None)
        if not match:
            raise HTTPException(404, f"version {version} not found")
        return match.model_dump(mode="json")
    return versions[-1].model_dump(mode="json")


@app.put("/personas/{persona_id}")
async def update_persona(
    persona_id: str, draft: PersonaDraft, level: str = "minor", p: Principal = Depends(principal)
) -> dict:
    versions = await _versions(p.tenant, persona_id)
    if not versions:
        raise HTTPException(404, "persona not found")
    prev = versions[-1]
    new_version = draft.version if draft.version != prev.version else bump(prev.version, level)
    data = draft.model_dump()
    data["version"] = new_version
    persona = Persona(
        id=persona_id, created_at=prev.created_at, created_by=prev.created_by,
        updated_at=iso(), **{k: v for k, v in data.items() if k != "version"}, version=new_version,
    )
    await _store(p.tenant, persona)
    return persona.model_dump(mode="json")


@app.delete("/personas/{persona_id}", status_code=204)
async def delete_persona(persona_id: str, p: Principal = Depends(principal)) -> None:
    versions = await _versions(p.tenant, persona_id)
    if not versions:
        raise HTTPException(404, "persona not found")
    latest = versions[-1]
    latest.archived = True
    await _store(p.tenant, latest)
