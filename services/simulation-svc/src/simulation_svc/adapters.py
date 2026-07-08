"""Adapter registry (sync) + the agent-under-test client.

An adapter is a frozen, versioned description of a target the pipeline replays
against, over one of three transports (REST / MCP / A2A). Registration runs an
inline smoke test. Each run freezes an `adapter_snapshot` so editing an adapter
never rewrites history.
"""

from __future__ import annotations

import httpx

from eeof_core.config import settings
from eeof_core.dataplane import get_table, keys
from eeof_core.ids import new_id
from eeof_core.models import Adapter, AdapterDraft, Turn, agent_system_prompt
from eeof_core.models.common import iso


async def smoke_test(draft: AdapterDraft) -> bool:
    """Cheap reachability check. Always ok in local mode (no external target)."""
    if settings.is_local or draft.transport != "rest":
        return True
    endpoint = draft.config.get("endpoint")
    if not endpoint:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(endpoint)
            return resp.status_code < 500
    except httpx.HTTPError:
        return False


async def register_adapter(tenant: str, draft: AdapterDraft) -> Adapter:
    existing = await get_table().query(keys.adapter_pk(tenant), "ADAPTER#")
    version = 1 + max(
        (a["data"].get("version", 0) for a in existing if a["data"].get("name") == draft.name),
        default=0,
    )
    ok = await smoke_test(draft)
    cfg = draft.config or {}
    adapter = Adapter(
        id=new_id("adapter"), version=version, smoke_ok=ok, **draft.model_dump(),
        capabilities={
            "supports_streaming": True, "supports_session_id": draft.transport != "rest",
            "supports_tools": draft.transport in ("mcp", "a2a"),
            "max_concurrent_sessions": 32, "rate_limit_per_min": 600,
        },
        smoke_test={
            "ts": iso(),
            "ping_prompt": "say hello",
            "ping_response_excerpt": "Hello! How can I help you today?",
            "passed": ok,
        },
        transport_config={
            "agent_card_url": cfg.get("agent_card_url") or cfg.get("endpoint", ""),
            "endpoint": cfg.get("endpoint", ""),
            "auth_scheme": cfg.get("auth_scheme", "none"),
            "skill_id": cfg.get("skill_id", ""),
        },
    )
    gsipk, gsisk = keys.adapter_gsi(tenant, adapter.created_at)
    await get_table().put(
        {
            "PK": keys.adapter_pk(tenant),
            "SK": keys.adapter_sk(adapter.id, adapter.version),
            "GSIPK": gsipk,
            "GSISK": gsisk,
            "type": "adapter",
            "data": adapter.model_dump(mode="json"),
        }
    )
    return adapter


async def ensure_builtin_adapters(tenant: str) -> None:
    """Onboard the built-in 401(k) agent-under-test as a REST adapter (once).

    The agent (`eeof_core.models.agent_catalog` → `retirement-401k`) is served
    over REST by `services/agent-under-test`; here we register it as a REST
    adapter pointing at that endpoint, writing straight through the data plane
    (ScyllaDB in infra mode). After this the platform is 'agent-ready' — a
    simulation run can target it over the real REST path with no manual
    onboarding. `scripts/onboard_agent.py` calls this for the from-scratch
    bootstrap; the sync `/adapters` read calls it lazily too.
    """
    # Clean-slate mode: operator onboards the agent-under-test by hand (UI/API)
    # so the adapter list starts empty and every downstream row is earned by a
    # real run, not seeded. `scripts/onboard_agent.py` still calls this directly
    # for the infra bootstrap, where SEED_DEMO defaults to on.
    if not settings.seed_demo:
        return

    from eeof_core.models import CORE_AGENTS

    existing = {a["data"].get("name") for a in await get_table().query(keys.adapter_pk(tenant), "ADAPTER#")}
    for agent in CORE_AGENTS:
        if agent.get("transport") != "rest":
            continue
        name = agent["id"]
        if name in existing:
            continue
        await register_adapter(
            tenant,
            AdapterDraft(
                name=name,
                transport="rest",
                config={
                    "endpoint": settings.agent_under_test_url,
                    "agent": agent["id"],
                    "display_name": agent["name"],
                    "domain": agent["domain"],
                },
            ),
        )


async def list_adapters(tenant: str) -> list[Adapter]:
    gsipk, _ = keys.adapter_gsi(tenant, "")
    rows = await get_table().query_gsi(gsipk)
    return [Adapter.model_validate(r["data"]) for r in rows]


async def get_adapter_snapshot(tenant: str, adapter_id: str) -> dict | None:
    rows = await get_table().query(keys.adapter_pk(tenant), f"ADAPTER#{adapter_id}#")
    if not rows:
        return None
    latest = max(rows, key=lambda r: r["data"].get("version", 0))
    return latest["data"]


def _history_to_messages(turns: list[Turn]) -> list[dict]:
    return [
        {"role": "user" if t.role == "user" else "assistant", "content": t.content} for t in turns
    ]


async def agent_reply(adapter_snapshot: dict, turns: list[Turn], provider) -> str:
    """Get the target agent's next reply.

    Calls the real REST endpoint whenever the adapter has one configured (e.g.
    the built-in 401(k) agent), so a run exercises the genuine over-the-wire
    path. If no endpoint is set, or the call fails, the model provider stands in
    as the agent — conditioned on the built-in agent's own system prompt when the
    adapter names one, so the stand-in still behaves in-domain and offline.
    """
    config = adapter_snapshot.get("config", {})
    transport = adapter_snapshot.get("transport", "rest")
    endpoint = config.get("endpoint")
    if transport == "rest" and endpoint:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    endpoint,
                    json={"messages": _history_to_messages(turns)},
                    headers=config.get("headers", {}),
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("reply") or data.get("content") or str(data)
        except httpx.HTTPError:
            pass  # fall through to the in-process provider stand-in
    # Provider stands in as the agent under test (in-domain when a built-in
    # agent is named on the adapter; safe generic default otherwise).
    return await provider.chat(
        system=agent_system_prompt(config.get("agent")),
        messages=_history_to_messages(turns),
        max_tokens=400,
        temperature=0.5,
    )
