"""Create the ScyllaDB table + GSI and the MinIO bucket (APP_ENV=infra).

Run once after `docker compose up -d` and before starting services with
APP_ENV=infra. Idempotent — safe to re-run.

    APP_ENV=infra uv run python scripts/init_infra.py
"""

from __future__ import annotations

from eeof_core.config import settings


def main() -> None:
    if settings.is_local:
        print("APP_ENV=local — nothing to init (in-memory plane). Set APP_ENV=infra first.")
        return
    from eeof_core.dataplane.blob import S3Blob
    from eeof_core.dataplane.table import ScyllaTable

    table = ScyllaTable()
    table.ensure_table()
    print(f"✓ table '{settings.scylla_table}' + GSI1 ready at {settings.scylla_endpoint}")

    blob = S3Blob()
    blob.ensure_bucket()
    print(f"✓ bucket '{settings.s3_bucket}' ready at {settings.s3_endpoint}")


if __name__ == "__main__":
    main()
