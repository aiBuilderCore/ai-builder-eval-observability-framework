"""Self-Heal control-plane store — incidents, policies, action registry, quality.

Like the other capability services, the high-value control-plane metadata lives
in the single table. Seed data is written once per tenant on first access
(idempotent), mirroring how simulation-svc lazily seeds its built-in adapters so
`APP_ENV=local` boots with a populated queue and the dashboard is never empty.
"""

from __future__ import annotations

from eeof_core.config import settings
from eeof_core.dataplane import get_table, keys
from eeof_core.models import (
    Policy,
    RemediationAction,
    SelfHealIncident,
    SelfHealSummary,
)

from .seed import SEED_ACTIONS, SEED_INCIDENTS, SEED_POLICIES

# Median MTTR is a rolling aggregate the worker would maintain; used as a demo
# figure only when there are actually resolved incidents to attribute it to.
_MEDIAN_MTTR = "18m"


def _status_of(inc: dict) -> str:
    return inc.get("status", "open")


async def ensure_seeded(tenant: str) -> None:
    """Write the synthetic seed once. Safe to call on every startup/request."""
    existing = await get_table().query(keys.heal_incident_pk(tenant), "HEAL_INCIDENT#")
    if existing:
        return
    # Clean-slate mode: no synthetic incident backlog — incidents should only
    # appear once a real quality breach is detected from an actual run. The
    # policy + action-registry vocabulary still loads: it is built-in config
    # (like the persona/judge libraries), not runtime data.
    seed_incidents = SEED_INCIDENTS if settings.seed_demo else []
    for inc in seed_incidents:
        model = SelfHealIncident.model_validate(inc)
        gsipk, gsisk = keys.heal_incident_gsi(tenant, model.status, model.opened_at)
        await get_table().put({
            "PK": keys.heal_incident_pk(tenant),
            "SK": keys.heal_incident_sk(model.id),
            "GSIPK": gsipk, "GSISK": gsisk,
            "type": "heal_incident",
            "data": model.model_dump(mode="json"),
        })
    for pol in SEED_POLICIES:
        model = Policy.model_validate(pol)
        await get_table().put({
            "PK": keys.heal_policy_pk(tenant),
            "SK": keys.heal_policy_sk(model.name),
            "type": "heal_policy",
            "data": model.model_dump(mode="json"),
        })
    for act in SEED_ACTIONS:
        model = RemediationAction.model_validate(act)
        await get_table().put({
            "PK": keys.heal_action_pk(tenant),
            "SK": keys.heal_action_sk(model.id),
            "type": "heal_action",
            "data": model.model_dump(mode="json"),
        })


# --- Incidents ---
async def list_incidents(tenant: str, status: str | None = None) -> list[SelfHealIncident]:
    await ensure_seeded(tenant)
    rows = await get_table().query(keys.heal_incident_pk(tenant), "HEAL_INCIDENT#")
    incs = [SelfHealIncident.model_validate(r["data"]) for r in rows]
    if status:
        incs = [i for i in incs if i.status == status]
    return sorted(incs, key=lambda i: i.opened_at, reverse=True)


async def get_incident(tenant: str, incident_id: str) -> SelfHealIncident | None:
    await ensure_seeded(tenant)
    row = await get_table().get(keys.heal_incident_pk(tenant), keys.heal_incident_sk(incident_id))
    return SelfHealIncident.model_validate(row["data"]) if row else None


async def save_incident(tenant: str, inc: SelfHealIncident) -> None:
    gsipk, gsisk = keys.heal_incident_gsi(tenant, inc.status, inc.opened_at)
    await get_table().put({
        "PK": keys.heal_incident_pk(tenant),
        "SK": keys.heal_incident_sk(inc.id),
        "GSIPK": gsipk, "GSISK": gsisk,
        "type": "heal_incident",
        "data": inc.model_dump(mode="json"),
    })


# --- Policies / registry ---
async def list_policies(tenant: str) -> list[Policy]:
    await ensure_seeded(tenant)
    rows = await get_table().query(keys.heal_policy_pk(tenant), "HEAL_POLICY#")
    return [Policy.model_validate(r["data"]) for r in rows]


async def list_actions(tenant: str) -> list[RemediationAction]:
    await ensure_seeded(tenant)
    rows = await get_table().query(keys.heal_action_pk(tenant), "HEAL_ACTION#")
    return [RemediationAction.model_validate(r["data"]) for r in rows]


# --- Quality rollup (dashboard) ---
async def get_quality(tenant: str) -> dict:
    """Delegate to the shared rollup so quality is aggregated from real verdicts
    (by agent + by judge→pillar), never from stored constants."""
    from eeof_core.rollups import quality_rollup

    return await quality_rollup(tenant)


# --- Summary KPIs ---
async def summary(tenant: str) -> SelfHealSummary:
    incs = await list_incidents(tenant)
    policies = await list_policies(tenant)
    open_count = len([i for i in incs if i.status != "resolved"])
    resolved = [i for i in incs if i.status == "resolved"]
    # Derive from real incident rows: a clean slate (no resolved incidents)
    # reports 0 auto-resolved and no MTTR rather than a fabricated constant.
    return SelfHealSummary(
        open_incidents=open_count,
        auto_resolved_24h=len(resolved),
        median_mttr=_MEDIAN_MTTR if resolved else "—",
        active_policies=len(policies),
    )
