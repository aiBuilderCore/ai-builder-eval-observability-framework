"""judge-registry (sync) — the source of versioned (judge @ version) identifiers.

Judges are immutable + version-pinned; a shipped verdict set freezes the exact
judge_ids it used, so a later judge revision never rewrites past verdicts.
Folded into evaluation-svc per the spec's entity ownership.
"""

from __future__ import annotations

from eeof_core.dataplane import get_table, keys
from eeof_core.ids import new_id
from eeof_core.models import CORE_JUDGES, Judge, JudgeDraft, Jury, JuryDraft


async def create_judge(tenant: str, draft: JudgeDraft) -> Judge:
    existing = await get_table().query(keys.judge_pk(tenant), f"JUDGE#{draft.name}#")
    version = 1 + max((j["data"].get("version", 0) for j in existing), default=0)
    judge = Judge(id=new_id("judge"), version=version, **draft.model_dump())
    gsipk, gsisk = keys.judge_gsi(tenant, judge.created_at)
    await get_table().put(
        {
            "PK": keys.judge_pk(tenant),
            "SK": keys.judge_sk(judge.name, judge.version),
            "GSIPK": gsipk,
            "GSISK": gsisk,
            "type": "judge",
            "data": judge.model_dump(mode="json"),
        }
    )
    return judge


async def list_judges(tenant: str) -> list[Judge]:
    gsipk, _ = keys.judge_gsi(tenant, "")
    rows = await get_table().query_gsi(gsipk)
    return [Judge.model_validate(r["data"]) for r in rows]


async def resolve_judge(tenant: str, ref: str) -> Judge | None:
    """Resolve 'name@vN' or 'name' (latest) to a Judge."""
    name, _, ver = ref.partition("@")
    rows = await get_table().query(keys.judge_pk(tenant), f"JUDGE#{name}#")
    if not rows:
        return None
    judges = [Judge.model_validate(r["data"]) for r in rows]
    if ver:
        wanted = int(ver.lstrip("v"))
        match = next((j for j in judges if j.version == wanted), None)
        return match
    return max(judges, key=lambda j: j.version)


async def create_jury(tenant: str, draft: JuryDraft) -> Jury:
    panel_id = draft.panel_id or new_id("jury")
    jury = Jury(**{**draft.model_dump(), "panel_id": panel_id})
    await get_table().put(
        {
            "PK": keys.jury_pk(tenant),
            "SK": keys.jury_sk(panel_id),
            "type": "jury",
            "data": jury.model_dump(mode="json"),
        }
    )
    return jury


async def get_jury(tenant: str, panel_id: str) -> Jury | None:
    row = await get_table().get(keys.jury_pk(tenant), keys.jury_sk(panel_id))
    return Jury.model_validate(row["data"]) if row else None


async def ensure_builtin_judges(tenant: str) -> None:
    """Seed the versioned built-in catalog the first time a tenant is used.

    The catalog is the authoritative research-grounded set in
    `eeof_core.models.judge_catalog.CORE_JUDGES`; each entry carries its full
    card metadata (dimension, family, turn types, reference requirement, cost,
    pattern, blurb, threshold) so `GET /judges` serves the same catalog the
    Evaluation wizard and Judge Catalogue screen render.
    """
    existing = {j.name for j in await list_judges(tenant)}
    for spec in CORE_JUDGES:
        if spec["name"] not in existing:
            await create_judge(tenant, JudgeDraft(**spec))
