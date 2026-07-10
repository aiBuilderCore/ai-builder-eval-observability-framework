"""Internal service clients — the edge proxies sync ops to capability services.

The orchestrator is the only public surface; it forwards the resolved
tenant/workspace as headers to internal services (which trust them because they
are unreachable from outside the cluster).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from eeof_core.config import settings
from eeof_core.context import forward_headers
from eeof_core.models import Principal


def _url(port: int) -> str:
    # In both local and infra the services resolve on localhost/compose DNS by port.
    host = "127.0.0.1"
    return f"http://{host}:{port}"


SERVICES = {
    "persona": _url(settings.persona_svc_port),
    "simulation": _url(settings.simulation_svc_port),
    "evaluation": _url(settings.evaluation_svc_port),
    "judge-registry": _url(settings.evaluation_svc_port),  # folded into evaluation-svc
    "observability": _url(settings.observability_svc_port),
    "self-heal": _url(settings.self_heal_svc_port),
}


# One shared client for the process lifetime. Creating a client per call opened
# (and immediately tore down) a fresh loopback TCP connection for every proxied
# request — cheap on macOS but a real per-request penalty on Windows, where a
# single page's 6-13 API calls each paid the connect/teardown cost. A shared
# client keeps connections warm and pooled, so repeat calls reuse a live socket.
# Bound + closed by the edge app lifespan (see app.py).
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(max_keepalive_connections=64, keepalive_expiry=30.0),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def proxy(
    service: str,
    method: str,
    path: str,
    principal: Principal,
    *,
    json: Any = None,
    params: dict | None = None,
) -> Any:
    base = SERVICES[service]
    client = get_client()
    try:
        resp = await client.request(
            method,
            f"{base}{path}",
            json=json,
            params=params,
            headers=forward_headers(principal),
        )
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{service} unreachable: {e}") from e
    if resp.status_code >= 400:
        detail = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise HTTPException(resp.status_code, detail)
    if resp.status_code == 204:
        return None
    return resp.json()
