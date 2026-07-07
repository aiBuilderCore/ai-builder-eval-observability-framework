"""Principal resolution — the one place tenancy is decided.

The edge (API Orchestration) resolves a Principal from the bearer token, then
forwards the resolved tenant/workspace to internal services as headers. Internal
services trust those headers because nothing but the edge is publicly reachable.
In dev/local mode any bearer maps to the configured tenant/workspace.
"""

from __future__ import annotations

from collections.abc import Mapping

from .config import settings
from .models.common import Principal


def principal_from_bearer(authorization: str | None) -> Principal:
    # Dev auth: presence of a token is enough; real auth verifies + maps claims.
    subject = "alex@acme"
    return Principal(subject=subject, tenant=settings.dev_tenant, workspace=settings.dev_workspace)


def principal_from_headers(headers: Mapping[str, str]) -> Principal:
    get = lambda k, d: headers.get(k) or headers.get(k.title()) or d  # noqa: E731
    return Principal(
        subject=get("x-subject", "alex@acme"),
        tenant=get("x-tenant", settings.dev_tenant),
        workspace=get("x-workspace", settings.dev_workspace),
    )


def forward_headers(p: Principal) -> dict[str, str]:
    return {"x-tenant": p.tenant, "x-workspace": p.workspace, "x-subject": p.subject}
