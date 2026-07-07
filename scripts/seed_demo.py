"""Seed the realistic demo dataset (idempotent).

Writes one end-to-end lineage per demo agent — seed set → run → verdict set +
per-judge verdicts → batch — so the dashboard's derived rollups (quality, spend,
self-heal) aggregate from real records. `run_all.py` calls this automatically on
`local` boot; run it by hand for `APP_ENV=infra`:

    APP_ENV=infra uv run python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio

from eeof_core.config import settings
from eeof_core.seed_demo import ensure_demo_data


async def main() -> None:
    result = await ensure_demo_data(settings.dev_tenant, settings.dev_workspace)
    if result.get("seeded"):
        print(
            f"✓ seeded demo lineage for tenant '{settings.dev_tenant}': "
            f"{result['runs']} runs · {result['verdict_sets']} verdict sets · "
            f"{result['verdicts']} verdicts · {result['batches']} batches"
        )
    else:
        print(f"demo data already present ({result.get('reason')}) — nothing to do.")


if __name__ == "__main__":
    asyncio.run(main())
