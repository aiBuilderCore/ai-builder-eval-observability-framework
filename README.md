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
> whole pipeline boots in one process. Flip `APP_ENV=infra` to point the
> identical code at the real backends via docker-compose.

## Quickstart

**One command, from scratch** — creates `.env`, installs every dependency,
(optionally) brings up ScyllaDB/NATS/MinIO, onboards the built-in **401(k)
retirement-planning agent** as a REST adapter directly into ScyllaDB, and runs
the whole integrated stack:

```bash
./bootstrap.sh          # infra mode (docker) if available, else falls back to local
./bootstrap.sh local    # zero-infra, in-memory data plane
```

**Or the bare local path** (no infra, no script):

```bash
uv sync --group dev
uv run python scripts/run_all.py       # boots all services in one process
```

Then either open the **control center** at <http://127.0.0.1:8080/> and click
through the five stages, or drive it headless:

```bash
uv run python scripts/demo.py          # persona → … → evidence, end to end
uv run pytest                          # unit + in-process pipeline tests
```

## Complete setup

### Prerequisites

| Tool | Why | Install |
|---|---|---|
| **[uv](https://docs.astral.sh/uv/)** | Python 3.13 workspace + deps | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (bootstrap installs it if missing) |
| **Docker** (+ compose) | only for `infra` mode (ScyllaDB / NATS / MinIO) | Docker Desktop or engine |
| **Azure OpenAI GPT-4** deployment | only for real model output | an Azure resource + a `gpt-4` deployment |

Nothing else is required for `local` mode — no database, no broker, no API key.

### 1. Configure (`.env`)

`bootstrap.sh` copies `.env.example` → `.env` on first run; you can also do it by
hand. The whole system is env-driven — no model or backend is hard-coded.

```bash
cp .env.example .env
```

Key switches:

- `APP_ENV` — `local` (in-memory data plane, default) or `infra` (real backends).
- `MODEL_PROVIDER` — `azure_openai` (**GPT-4, default**), `anthropic`, `bedrock`,
  or `echo`. When `azure_openai` is selected but the three `AZURE_OPENAI_*` vars
  are blank, it **falls back to `echo`** automatically, so it always boots.

To use real **Azure OpenAI GPT-4**, fill in:

```bash
MODEL_PROVIDER=azure_openai
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4          # your deployment name
```

### 2. Bring it up

**From scratch, one command** (recommended):

```bash
./bootstrap.sh            # infra if docker is present, else local; onboards the 401k agent
./bootstrap.sh local      # force zero-infra
./bootstrap.sh infra      # force real ScyllaDB + NATS + MinIO
./bootstrap.sh infra --no-run   # set up everything but don't start services
```

`bootstrap.sh` is idempotent and does, in order: create/refresh `.env` → install
all deps (core, every service, the 401k agent; the frontend is static, no JS
build) → in `infra` mode `docker compose up -d`, wait for ScyllaDB,
`init_infra.py` (table + GSI + bucket), then **onboard the 401k agent as a REST
adapter directly into ScyllaDB** → run the full stack.

**Manual local:**

```bash
uv sync --group dev
uv run python scripts/run_all.py
```

**Manual infra:**

```bash
uv sync --group dev --group infra --group llm
docker compose up -d
APP_ENV=infra uv run python scripts/init_infra.py
APP_ENV=infra uv run python scripts/onboard_agent.py   # 401k agent → ScyllaDB
APP_ENV=infra uv run python scripts/run_all.py
```

### 3. Use it

- **Control center (SPA + API):** <http://127.0.0.1:8080/>
- **Edge API:** <http://127.0.0.1:8080/api/v1> (bearer `dev` in local mode)
- **401k agent-under-test (REST):** <http://127.0.0.1:8097/chat>
- **End-to-end demo:** `uv run python scripts/demo.py`
- **Run a sweep against the 401k agent:** in Simulation, pick a financial persona
  (e.g. *First-Timer Femi*) and the `retirement-401k` adapter, then evaluate with
  the `finance-guardrail` panel.
- **Tests / lint:** `uv run pytest` · `uv run ruff check .`

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
| **Evaluation** | submit → real jury scoring, verdict sets with per-juror verdicts, run picker, live **judge catalogue** (sync registry) |
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
| `agent-under-test` | **sync** REST target (demo 401k agent) | 8097 | — | — |

The `agent-under-test` service is the *target being evaluated*, not part of the
control plane — a demo **401(k) retirement-planning assistant** exposing
`POST /chat`. simulation-svc onboards it as a REST adapter (seeded from
`CORE_AGENTS`) so a run drives it turn-by-turn over the wire.

¹ The judge registry is co-hosted in `evaluation-svc` (which owns Judge/Jury per
the spec's entity map); `8092` is its logical port. Everything else maps 1:1 to
the service registry.

## Repo layout

```
packages/core/            shared library (eeof_core)
  models/                 Pydantic contracts + built-in catalogs:
                            judge_catalog (CORE_JUDGES incl. finance guardrails),
                            persona_catalog (CORE_PERSONAS), agent_catalog (CORE_AGENTS)
  dataplane/              table.py · bus.py · blob.py · keys.py  (in-memory | real)
  providers/              azure_openai/GPT-4 (default) · anthropic · bedrock · echo
  jobs.py · worker.py     uniform Job lifecycle + BaseWorker
  messaging.py · ids.py · config.py · context.py
services/                 the runtime services (FastAPI apps / workers),
                            incl. agent-under-test (the demo 401k REST agent)
frontend-web/             control-center SPA (REST + one WebSocket)
scripts/                  bootstrap flow: run_all · demo · init_infra · onboard_agent
bootstrap.sh              one-command from-scratch: .env + deps + infra + onboard + run
tests/                    unit + in-process pipeline
docker-compose.yml        ScyllaDB (Alternator) + NATS JetStream + MinIO
```

### Built-in catalogs & the 401k demo agent

Three research-/domain-grounded catalogs seed every tenant idempotently on first
access, mirroring how the judge registry seeds itself:

- **Judges** (`GET /judges`) — the core catalog plus finance guardrail judges:
  `no_financial_advice`, `regulatory_disclosure`, and the non-LLM
  `numeric_accuracy` verifier, grouped by the `finance-guardrail` panel.
- **Personas** (`GET /personas`, seeded by persona-svc) — a diverse
  agent-testing set (adversarial, frustrated, novice, power-user, compliance-bait)
  plus three financial personas that exercise the 401k agent. No multilingual
  personas — locale coverage is out of scope.
- **Agents** (`CORE_AGENTS`) — the 401k retirement-planning **agent-under-test**,
  onboarded as a REST adapter and served by `agent-under-test`. It must educate
  without giving individualized investment advice — exactly what the finance
  judges + financial personas stress.

**Multi-turn is history-grounded:** the user-simulator generates each turn *n*
follow-up from the full transcript so far (turns 1..n-1) plus the persona's goal
and edge-case, so every message is a real reaction to the agent's last reply.

## Model providers (LLM usage)

Every heavy stage (question authoring, user-simulator, judge scoring, and the
401k agent-under-test) calls a `ModelProvider` — never a vendor SDK directly, and
nothing hard-codes a model. Select the backend with `MODEL_PROVIDER`; each real
backend is invoked over its own API:

| `MODEL_PROVIDER` | Backend | Needs |
|---|---|---|
| `azure_openai` *(default)* | Azure OpenAI Chat Completions, **GPT-4** | `AZURE_OPENAI_ENDPOINT` / `_API_KEY` / `_DEPLOYMENT` |
| `anthropic` | Anthropic Messages API | `uv sync --group llm`, `ANTHROPIC_API_KEY` |
| `bedrock` | AWS Bedrock Converse API | `uv sync --group infra`, AWS creds, `BEDROCK_MODEL_ID` |
| `echo` | deterministic, offline, reproducible | nothing |

The default is **Azure OpenAI GPT-4**, configured entirely through `.env` (see
`.env.example`). When its credentials are blank the provider factory transparently
falls back to the deterministic `echo` provider, so a from-scratch checkout /
`bootstrap.sh` still runs fully offline and reproducibly — swapping to real GPT-4
is just filling in three env vars.

## Running against real infra

```bash
docker compose up -d                                   # scylla + nats + minio
APP_ENV=infra uv run python scripts/init_infra.py      # create table+GSI, bucket
APP_ENV=infra uv run python scripts/onboard_agent.py   # 401k agent → REST adapter in ScyllaDB
# then start each service in its own shell (or a process manager):
APP_ENV=infra uv run python -m api_orchestration
APP_ENV=infra uv run python -m persona_svc
APP_ENV=infra uv run python -m qgen_svc
APP_ENV=infra uv run python -m simulation_svc
APP_ENV=infra uv run python -m evaluation_svc
APP_ENV=infra uv run python -m observability_svc
APP_ENV=infra uv run python -m agent_under_test        # the 401k agent-under-test
```

(Or just `./bootstrap.sh infra`, which does all of the above in one shot.)

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
