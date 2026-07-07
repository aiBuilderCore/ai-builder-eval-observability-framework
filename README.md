# Enterprise Eval Observability Framework

End-to-end microservice implementation of the five-stage eval pipeline —
**persona → question → run → verdict → evidence** — built to the
[architecture guide](../ai-builder-artifacts/architecture-guides/enterprise-eval-observability-framework/)
and [implementation specs](../ai-builder-artifacts/implementation-guides/enterprise-eval-observability-framework/),
with the [clickable mocks](../ai-builder-artifacts/applications/enterprise-eval-observability-framework/)
as the UI reference.

One **API Orchestration Service** is the only public edge (REST + WebSocket).
Behind it, lightweight work resolves synchronously against the database; heavy
work is accepted synchronously (`202 + job_id`) and executed off a **NATS
JetStream** queue by capability workers, with live progress streamed back over a
WebSocket. State lives in a single **ScyllaDB** table; large immutable payloads
live in **MinIO/S3**.

> **Runs with zero infra.** `APP_ENV=local` (the default) swaps ScyllaDB / NATS /
> MinIO for in-process equivalents behind the same interfaces, so the whole
> eight-service pipeline boots in one process. Flip `APP_ENV=infra` to point the
> identical code at the real backends via docker-compose.

## Quickstart (local, no dependencies)

```bash
uv sync --group dev
uv run python scripts/run_all.py       # boots all 8 services in one process
```

Then either open the **control center** at <http://127.0.0.1:8080/> and click
through the five stages, or drive it headless:

```bash
uv run python scripts/demo.py          # persona → … → evidence, end to end
uv run pytest                          # unit + in-process pipeline tests
```

## Frontend (live SPA)

`frontend-web/` is the five-app control center (ported from the design mocks),
served single-origin by the edge at <http://127.0.0.1:8080/>. Each app has a
`LIVE wiring` adapter in its `app.js` that maps the API into the UI shapes and
falls back to seed data when the edge is unreachable, so the UI never blanks.

| Surface | Live against the API |
|---|---|
| **Dashboard** | KPIs (personas, seed sets, runs, verdicts, pass-rate, open flags) + jobs table |
| **Persona Lab** | full CRUD (`/personas`) — gallery, create, edit, delete, versioning |
| **Question Generation** | submit → real `qgen` job, phase-level progress, seed-set questions |
| **Simulation** | adapter onboarding, submit → real run, run detail (tokens/stop-reasons), trace turns |
| **Evaluation** | submit → real jury scoring, verdict sets with per-juror verdicts, run picker |
| **Observability** | monitors, evidence packs, judge-κ calibration (control-plane) |

**Illustrative (no backend source yet):** batch span-trees, OpenInference
trajectory, drift heatmaps, and the compliance-template detail — these need
span/drift features beyond the current services and keep seed data. The shared
client is `frontend-web/_api.js` (REST + one multiplexed WebSocket). Static
assets are served no-cache in dev so edits show up on reload.

## Services

| Service | Mode | Port | Consumes | Publishes |
|---|---|---|---|---|
| `api-orchestration` | edge (REST + WS) | 8080 | `status.*` | `qgen.jobs`, `sim.jobs`, `eval.jobs`, `obs.jobs` |
| `persona-svc` | **sync** | 8091 | — | — |
| `judge-registry` | **sync** (folded into evaluation-svc) | 8092¹ | — | — |
| `qgen-svc` | **async** worker | 8093 | `qgen.jobs` | `status.qgen.*` |
| `simulation-svc` | **async** worker + sync adapters | 8094 | `sim.jobs` | `status.sim.*`, `trace.events.*` |
| `evaluation-svc` | **async** worker + judge registry | 8095 | `eval.jobs` | `status.eval.*` |
| `observability-svc` | **async / streaming** + read API | 8096 | `trace.events.*`, `obs.jobs` | `status.obs.*` |

¹ The judge registry is co-hosted in `evaluation-svc` (which owns Judge/Jury per
the spec's entity map); `8092` is its logical port. Everything else maps 1:1 to
the service registry.

## Repo layout

```
packages/core/            shared library (eeof_core)
  models/                 Pydantic contracts (persona, seedset, run, verdict, …)
  dataplane/              table.py · bus.py · blob.py · keys.py  (in-memory | real)
  providers/              echo (default) · anthropic · bedrock · azure_openai
  jobs.py · worker.py     uniform Job lifecycle + BaseWorker
  messaging.py · ids.py · config.py · context.py
services/                 the 8 runtime services (FastAPI apps / workers)
frontend-web/             control-center SPA (REST + one WebSocket)
scripts/                  run_all · demo · init_infra
tests/                    unit + in-process pipeline
docker-compose.yml        ScyllaDB (Alternator) + NATS JetStream + MinIO
```

## Model providers (LLM usage)

Every heavy stage (question authoring, user-simulator, judge scoring) calls a
`ModelProvider` — never a vendor SDK directly. Select the backend with
`MODEL_PROVIDER`; each real backend is invoked over its own API:

| `MODEL_PROVIDER` | Backend | Needs |
|---|---|---|
| `echo` *(default)* | deterministic, offline, reproducible | nothing |
| `anthropic` | Anthropic Messages API | `uv sync --group llm`, `ANTHROPIC_API_KEY` |
| `bedrock` | AWS Bedrock Converse API | `uv sync --group infra`, AWS creds, `BEDROCK_MODEL_ID` |
| `azure_openai` | Azure OpenAI Chat Completions (REST) | `AZURE_OPENAI_ENDPOINT` / `_API_KEY` / `_DEPLOYMENT` |

The deterministic `echo` provider keeps the pipeline runnable and reproducible
with no API key; swapping to a real model is one env var. See `.env.example`.

## Running against real infra

```bash
docker compose up -d                                   # scylla + nats + minio
APP_ENV=infra uv run python scripts/init_infra.py      # create table+GSI, bucket
# then start each service in its own shell (or a process manager):
APP_ENV=infra uv run python -m api_orchestration
APP_ENV=infra uv run python -m persona_svc
APP_ENV=infra uv run python -m qgen_svc
APP_ENV=infra uv run python -m simulation_svc
APP_ENV=infra uv run python -m evaluation_svc
APP_ENV=infra uv run python -m observability_svc
```

The service code is identical across modes — only the data-plane and provider
factories branch on config.

## Design notes

- **Immutable + versioned.** Personas, seed sets, runs, verdicts, evidence packs
  are append-only; downstream stages freeze `(id, version)` / snapshots into the
  job envelope, so any historical decision reconstructs exactly.
- **The queue is the accept/execute seam.** The edge never calls a worker
  directly — it writes a `queued` Job and publishes to a JOBS subject; a worker
  acks only after durable output, and outputs are `config_hash`-keyed so
  redelivery is idempotent.
- **Single-table access.** Every read is a key lookup or one GSI query — key
  builders live in `packages/core/.../dataplane/keys.py`.
- **Tenancy is physical.** The tenant is the top-level partition prefix on every
  key; the edge resolves it and forwards it to internal services.

## Conventions

- `uv run` for every Python invocation. `pyproject.toml` (a uv workspace) is the
  single source of truth for deps; don't hand-edit `uv.lock`.
- Lint/format: `uv run ruff check .` / `uv run ruff format .`
- **Synthetic data only** — no real customer data anywhere, including demos.
