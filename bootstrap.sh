#!/usr/bin/env bash
#
# bootstrap.sh — one command to stand up the Enterprise Eval Observability
# Framework from scratch: create .env, install every dependency (core, all
# services, frontend, and the 401(k) agent-under-test), bring up infrastructure,
# onboard the agent as a REST adapter directly into ScyllaDB, and run the whole
# integrated stack (backend + frontend, served single-origin by the edge).
#
# Usage:
#   ./bootstrap.sh                 # mode from .env APP_ENV, else 'infra'
#   ./bootstrap.sh infra           # real ScyllaDB + NATS + MinIO via docker
#   ./bootstrap.sh local           # zero-infra, in-memory data plane
#   ./bootstrap.sh infra --no-run  # set everything up but don't start services
#
# Idempotent: safe to re-run. Preserves an existing .env (only fills APP_ENV).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ---------------------------------------------------------------------------
# 0. Args / mode
# ---------------------------------------------------------------------------
MODE=""
RUN=1
for arg in "$@"; do
  case "$arg" in
    local|infra) MODE="$arg" ;;
    --no-run)    RUN=0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m›\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. .env — create from example if missing, then pin APP_ENV
# ---------------------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  log "created .env from .env.example"
else
  log ".env already present — keeping it"
fi

# Resolve mode: explicit arg > existing .env value > default 'infra'
if [ -z "$MODE" ]; then
  MODE="$(grep -E '^APP_ENV=' .env | head -1 | cut -d= -f2 | tr -d '[:space:]' || true)"
  MODE="${MODE:-infra}"
fi

# Write APP_ENV back into .env (portable in-place edit)
if grep -qE '^APP_ENV=' .env; then
  tmp="$(mktemp)"; sed "s/^APP_ENV=.*/APP_ENV=$MODE/" .env > "$tmp" && mv "$tmp" .env
else
  printf '\nAPP_ENV=%s\n' "$MODE" >> .env
fi
log "APP_ENV=$MODE"

# ---------------------------------------------------------------------------
# 2. Dependencies — uv installs core + all services (incl. agent-under-test)
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing (https://astral.sh/uv)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1090
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

# NB: do not name this array `GROUPS` — that is a reserved bash variable (the
# current user's group IDs) and assignments to it are silently ignored.
SYNC_GROUPS=(--group dev)
if [ "$MODE" = "infra" ]; then
  SYNC_GROUPS+=(--group infra --group llm)   # nats/boto3 + real-LLM extras
fi
log "uv sync ${SYNC_GROUPS[*]}"
uv sync "${SYNC_GROUPS[@]}"
# The frontend is static (served by the edge) — no separate JS build/install.

# ---------------------------------------------------------------------------
# 3. Infrastructure (infra mode) — bring up backends, init schema, onboard agent
# ---------------------------------------------------------------------------
if [ "$MODE" = "infra" ]; then
  if ! command -v docker >/dev/null 2>&1; then
    warn "docker not found but APP_ENV=infra — falling back to local mode."
    MODE="local"
    tmp="$(mktemp)"; sed "s/^APP_ENV=.*/APP_ENV=local/" .env > "$tmp" && mv "$tmp" .env
  fi
fi

if [ "$MODE" = "infra" ]; then
  log "docker compose up -d (scylla + nats + minio)"
  docker compose up -d

  log "waiting for ScyllaDB Alternator on :8000 …"
  for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/ >/dev/null 2>&1; then break; fi
    sleep 2
    [ "$i" = 60 ] && { warn "ScyllaDB did not become ready in time"; exit 1; }
  done

  log "init_infra — create table + GSI + bucket"
  APP_ENV=infra uv run python scripts/init_infra.py

  log "onboard 401(k) agent as a REST adapter directly into ScyllaDB"
  APP_ENV=infra uv run python scripts/onboard_agent.py

  log "seed realistic demo lineage (runs + verdicts + batches) for the dashboard"
  APP_ENV=infra uv run python scripts/seed_demo.py
fi

# ---------------------------------------------------------------------------
# 4. Run the integrated stack (backend + frontend, one edge)
# ---------------------------------------------------------------------------
cat <<EOF

  Ready.
    mode        : $MODE
    control ctr : http://127.0.0.1:8080/            (SPA, served by the edge)
    edge API    : http://127.0.0.1:8080/api/v1
    self-heal   : http://127.0.0.1:8080/self-heal/  (closed-loop remediation)
    401k agent  : http://127.0.0.1:8097/chat        (REST agent-under-test)
    model       : Azure GPT-4 primary -> Groq fallback -> echo (set keys in .env)

  Initial data is seeded automatically: the dashboard + observability rollups
  (SEED_DEMO) and — once the edge is live — a real question-generation /
  simulation / evaluation / self-heal lineage driven through the API
  (scripts/seed_pipeline.py). Judge catalogue + persona lab come from the core
  library. To drive another lineage yourself:
    uv run python scripts/demo.py

EOF

if [ "$RUN" = 1 ]; then
  # Start the whole stack in the background so we can seed the interactive
  # surfaces (question-generation / simulation / evaluation / self-heal) through
  # the real edge once it is live, then hand the terminal back to the running
  # stack. SEED_HEAL_INCIDENTS=0 keeps Self-Heal populated only by the real
  # breach detector (no hand-written INC-99x incidents); SEED_DEMO (default on)
  # still seeds the dashboard/observability rollups + onboards the agent adapter.
  log "starting all services in the background …"
  SEED_HEAL_INCIDENTS=0 uv run python scripts/run_all.py &
  RUN_PID=$!
  # Stop the stack if bootstrap is interrupted before hand-off.
  trap 'kill "$RUN_PID" 2>/dev/null || true' INT TERM

  log "waiting for the edge on :8080 …"
  EDGE_UP=0
  for i in $(seq 1 60); do
    if ! kill -0 "$RUN_PID" 2>/dev/null; then
      warn "the stack exited during startup — see the logs above"; exit 1
    fi
    if curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then EDGE_UP=1; break; fi
    sleep 1
  done
  if [ "$EDGE_UP" = 1 ]; then
    log "seeding interactive pipeline data (qgen · sim · eval · self-heal) …"
    uv run python scripts/seed_pipeline.py || warn "pipeline seed skipped/failed (stack still up)"
  else
    warn "edge did not become ready in time — skipping pipeline seed"
  fi

  # Hand off: keep the stack in the foreground (Ctrl-C stops it).
  trap - INT TERM
  log "platform ready — http://127.0.0.1:8080/  (Ctrl-C to stop)"
  wait "$RUN_PID"
else
  log "--no-run: setup complete."
  log "  start the stack : uv run python scripts/run_all.py"
  log "  then seed it    : uv run python scripts/seed_pipeline.py"
fi
