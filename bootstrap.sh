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

GROUPS=(--group dev)
if [ "$MODE" = "infra" ]; then
  GROUPS+=(--group infra --group llm)   # nats/boto3 + real-LLM extras
fi
log "uv sync ${GROUPS[*]}"
uv sync "${GROUPS[@]}"
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
fi

# ---------------------------------------------------------------------------
# 4. Run the integrated stack (backend + frontend, one edge)
# ---------------------------------------------------------------------------
cat <<EOF

  Ready.
    mode        : $MODE
    control ctr : http://127.0.0.1:8080/            (SPA, served by the edge)
    edge API    : http://127.0.0.1:8080/api/v1
    401k agent  : http://127.0.0.1:8097/chat        (REST agent-under-test)

  In another shell you can drive the full pipeline end-to-end:
    uv run python scripts/demo.py

EOF

if [ "$RUN" = 1 ]; then
  log "starting all services (Ctrl-C to stop) …"
  exec uv run python scripts/run_all.py
else
  log "--no-run: setup complete. Start with: uv run python scripts/run_all.py"
fi
