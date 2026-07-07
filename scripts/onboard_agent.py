"""Onboard the built-in 401(k) agent-under-test as a REST adapter.

Writes the adapter straight through the data plane — in `APP_ENV=infra` that is a
direct row in ScyllaDB, so the moment the platform comes up a simulation run can
target the agent over REST with no manual onboarding step. Idempotent: re-running
never duplicates the adapter.

    APP_ENV=infra uv run python scripts/onboard_agent.py     # writes to ScyllaDB

In `APP_ENV=local` the data plane is in-memory and per-process, so onboarding is
handled lazily by simulation-svc on first `/adapters` read instead; this script
still runs and reports what it would register.
"""

from __future__ import annotations

import asyncio

from eeof_core.config import settings


async def main() -> None:
    from simulation_svc.adapters import ensure_builtin_adapters, list_adapters

    tenant = settings.dev_tenant
    if settings.is_local:
        print(
            "APP_ENV=local — the data plane is in-memory and per-process, so the "
            "adapter is seeded lazily by simulation-svc on first /adapters read. "
            "Set APP_ENV=infra to onboard directly into ScyllaDB."
        )

    await ensure_builtin_adapters(tenant)
    adapters = await list_adapters(tenant)
    print(f"✓ agent onboarded for tenant '{tenant}' → {settings.agent_under_test_url}")
    for a in adapters:
        print(f"    adapter: {a.name}  v{a.version}  transport={a.transport}  smoke_ok={a.smoke_ok}")


if __name__ == "__main__":
    asyncio.run(main())
