# ai-builder-eval-observability-framework

Runtime **implementation** of the Enterprise Eval Observability Framework — the
nine-service pipeline behind one API Orchestration edge. This is production-shaped
service code; the *specs* live in the sibling `ai-builder-artifacts` repo (see
`README.md` for the links). When behavior and spec disagree, the spec is the
source of truth — change code to match it, or change the spec deliberately and in
lockstep.

## Stack
- Python `>=3.13`, managed as a **uv workspace** (`packages/*` + `services/*`).
- FastAPI + uvicorn (edge REST/WS and each service), Pydantic v2 contracts.
- Pluggable data plane: in-memory (local) or ScyllaDB Alternator + NATS JetStream
  + MinIO (infra). Model providers: azure_openai (default primary) / groq (default
  fallback) / anthropic / bedrock / echo — all invoked over their API, never
  SDK-coupled in stage code. `get_provider()` builds a **fallback chain**
  (primary → `MODEL_FALLBACK` → echo), dropping any link whose creds are absent.

## Common commands
- Sync: `uv sync --group dev` (add `--group infra` / `--group llm` for real backends).
- Run all services locally (one process, in-memory plane): `uv run python scripts/run_all.py`.
- End-to-end demo: `uv run python scripts/demo.py`.
- Tests: `uv run pytest`. Lint: `uv run ruff check .`.
- Real infra: `docker compose up -d` then `APP_ENV=infra uv run python scripts/init_infra.py`.

## Architecture rules (do not drift)
- **The orchestrator is the only public edge.** Capability services are reachable
  only internally; the edge resolves tenancy from the bearer token and forwards
  `x-tenant`/`x-workspace` headers. Never expose a capability service publicly.
- **The orchestrator runs no domain logic.** Its async path only validates,
  *freezes* immutable snapshots into the job envelope, writes the `queued` Job,
  and publishes to a JOBS subject. All heavy logic lives in the worker.
- **Sync vs async is load-bearing.** Sync = validate-and-write inside the request
  (persona, adapter, judge/jury, monitor). Async = `202 + job_id`, executed off a
  queue (qgen, simulation, evaluation, evidence assembly).
- **Immutable + versioned everywhere.** Personas / seed sets / runs / verdicts /
  evidence packs are append-only; freeze `(id, version)` / snapshots downstream,
  never a mutable reference.
- **Config-hash idempotency.** Job outputs are keyed by `config_hash`; a resubmit
  of identical inputs returns the original `job_id`, and redelivery is a no-op.

## Where things live
- Contracts: `packages/core/src/eeof_core/models/`. Change a contract here first,
  then the services that read it, then mirror into the spec.
- Single-table keys: `packages/core/.../dataplane/keys.py` — one function per
  entity. Every new access pattern is a key builder here, not an ad-hoc string.
- Data plane / bus / blob: `packages/core/.../dataplane/`. Add a backend by
  implementing the ABC and wiring the `get_*()` factory; callers never branch.
- Model providers: `packages/core/.../providers/`. A new backend implements
  `chat`; judge `score` has a default. Register it in `providers/__init__.py`.
  Providers resolve through a **fallback chain** (primary → `MODEL_FALLBACK` →
  echo) built in `providers/__init__.py`.
- Dashboard rollups: `packages/core/.../rollups.py` — `quality_rollup` /
  `spend_rollup` aggregate real verdict/batch rows (never display constants),
  served at `/observability/quality` + `/observability/spend`. The judge→pillar
  map is `JUDGE_PILLARS` in `models/judge_catalog.py`.
- Demo seed: `packages/core/.../seed_demo.py` writes one real lineage per demo
  agent on boot (idempotent) so the derived rollups have rows to aggregate;
  `run_all.py` calls it, `scripts/seed_demo.py` is the standalone/infra entry.
- A service: `services/<name>/src/<pkg>/` with `app.py` (FastAPI) and, for async
  services, `worker.py` (a `BaseWorker` subclass) bound in the app lifespan.

## Adding an async stage
1. Contract in `core/models/`, keys in `core/dataplane/keys.py`.
2. Subject in `core/messaging.py` (`STREAMS`, `SUBMIT_SUBJECT`).
3. `services/<name>/…/worker.py` subclassing `BaseWorker` (`subject`, `durable`,
   `stage`, `handle`); bind it in the app lifespan.
4. Edge submission handler in `api-orchestration/.../app.py` that freezes inputs
   and calls `submit_job(...)`.
5. Test in `tests/` (drive `worker.handle` on the in-memory plane, deterministic
   via the echo provider). Run `uv run pytest` + `uv run ruff check .`.

## Frontend wiring (frontend-web/)

The SPA is served by the edge (`NoCacheStatic` mount). Each app is wired live by
a `LIVE wiring` adapter appended to its `app.js`, following one recipe:

1. **Shared client** `_api.js` exposes `window.EEOF` (REST + one WebSocket +
   `submitAndWatch`/`pollJob`). Every page must load `../_api.js` **before**
   `app.js` — mind query-string script srcs (`app.js?v=2`) when patching.
2. **Adapter** (IIFE, guarded by `if (!window.EEOF) return;`) keeps in-memory
   caches, a `hydrate()` that fetches + maps API → the app's UI shapes, and
   **overrides the app's data seam** (`PL.load`, `SIM.getRun`, `EV.getVerdictSet`,
   `AIBC_OBS.State.monitors`, …) to read those caches. Map, don't rename — the UI
   shapes are richer (nested `prompt_shape`/`scenario`, per-juror `judges`, phase
   detail); synthesize fields the API lacks.
3. **Repaint model.** Index/list pages use `startTicking(render)` (hydrate polls
   + re-renders). Read-once detail pages expose `<NS>.ready` (a promise resolved
   after first hydrate) and defer their init: `NS.ready.then(render)`. Never let a
   not-found guard redirect before hydrate — gate it on `window.EEOF`.
4. **Submit** flows branch to `<NS>.submitLive(...)` when `window.EEOF` is set,
   POSTing the real job and navigating to the (live) detail page.

Some analytical screens (span-trees, drift heatmaps, trajectory) have no backend
source and intentionally keep seed data — see the README table.

## Hard rules
- **Synthetic data only** — fabricated tenants (`acme`), personas, costs. Never
  real customer data, including in the SPA and demo.
- **Keep code and spec in lockstep.** A change to an endpoint, subject, or table
  key is breaking until proven additive; mirror it into the architecture guide
  and the stage spec in `ai-builder-artifacts`.
- **Don't hand-edit `uv.lock`.** `pyproject.toml` is the source of truth.
- Optional backends (nats/boto3/anthropic) are lazy-imported; local mode must
  keep booting with only the base + dev groups installed.
