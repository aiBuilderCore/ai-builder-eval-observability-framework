"""Boot the whole platform in one process (local mode).

In APP_ENV=local every service shares the same in-memory table/bus/blob
singletons, so the eight services form a working pipeline with zero external
infra. Each service's lifespan binds its workers/subscribers on startup.

    uv run python scripts/run_all.py

For the production-shaped path, bring up docker-compose (real ScyllaDB/NATS/MinIO)
and run each `python -m <service>` separately with APP_ENV=infra.
"""

from __future__ import annotations

import asyncio

import uvicorn

from eeof_core.config import settings


def _server(app, port: int) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )


async def main() -> None:
    from api_orchestration.app import app as orchestration
    from evaluation_svc.app import app as evaluation
    from observability_svc.app import app as observability
    from persona_svc.app import app as persona
    from qgen_svc.app import app as qgen
    from simulation_svc.app import app as simulation

    servers = [
        _server(persona, settings.persona_svc_port),
        _server(qgen, settings.qgen_svc_port),
        _server(simulation, settings.simulation_svc_port),
        _server(evaluation, settings.evaluation_svc_port),
        _server(observability, settings.observability_svc_port),
        _server(orchestration, settings.api_orchestration_port),
    ]
    print("eeof platform up (local mode):")
    print(f"  edge (REST+WS): http://127.0.0.1:{settings.api_orchestration_port}/api/v1")
    print(f"  persona :{settings.persona_svc_port}  qgen :{settings.qgen_svc_port}  "
          f"sim :{settings.simulation_svc_port}  eval :{settings.evaluation_svc_port}  "
          f"obs :{settings.observability_svc_port}")
    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(main())
