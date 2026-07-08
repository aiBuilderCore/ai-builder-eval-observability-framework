<#
.SYNOPSIS
  bootstrap.ps1 — Windows PowerShell counterpart of bootstrap.sh.

  One command to stand up the Enterprise Eval Observability Framework from
  scratch: create .env, install every dependency (core, all services, frontend,
  and the 401(k) agent-under-test), optionally bring up infrastructure, onboard
  the agent, start the integrated stack, and seed initial data across every
  surface (dashboard, question-generation, simulation, evaluation, observability,
  self-heal). Judge catalogue + persona lab come from the core library.

.EXAMPLE
  .\bootstrap.ps1                 # mode from .env APP_ENV, else 'infra'
  .\bootstrap.ps1 infra           # real ScyllaDB + NATS + MinIO via docker
  .\bootstrap.ps1 local           # zero-infra, in-memory data plane
  .\bootstrap.ps1 infra -NoRun    # set everything up but don't start services

  Idempotent: safe to re-run. Preserves an existing .env (only fills APP_ENV).
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('', 'local', 'infra')]
  [string]$Mode = '',
  [switch]$NoRun
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Log  ($m) { Write-Host "> $m" -ForegroundColor Cyan }
function Warn ($m) { Write-Host "! $m" -ForegroundColor Yellow }

# ---------------------------------------------------------------------------
# 1. .env — create from example if missing, then pin APP_ENV
# ---------------------------------------------------------------------------
if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Log "created .env from .env.example"
} else {
  Log ".env already present — keeping it"
}

# Resolve mode: explicit arg > existing .env value > default 'infra'
if (-not $Mode) {
  $line = Select-String -Path .env -Pattern '^APP_ENV=' | Select-Object -First 1
  if ($line) { $Mode = ($line.Line -split '=', 2)[1].Trim() }
  if (-not $Mode) { $Mode = 'infra' }
}

# Write APP_ENV back into .env
$envText = Get-Content .env -Raw
if ($envText -match '(?m)^APP_ENV=') {
  ($envText -replace '(?m)^APP_ENV=.*', "APP_ENV=$Mode").TrimEnd() + "`n" | Set-Content .env -NoNewline
} else {
  Add-Content .env "`nAPP_ENV=$Mode"
}
Log "APP_ENV=$Mode"

# ---------------------------------------------------------------------------
# 2. Dependencies — uv installs core + all services (incl. agent-under-test)
# ---------------------------------------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Warn "uv not found — installing (https://astral.sh/uv)"
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

$SyncGroups = @('--group', 'dev')
if ($Mode -eq 'infra') { $SyncGroups += @('--group', 'infra', '--group', 'llm') }
Log "uv sync $($SyncGroups -join ' ')"
uv sync @SyncGroups
# The frontend is static (served by the edge) — no separate JS build/install.

# ---------------------------------------------------------------------------
# 3. Infrastructure (infra mode) — bring up backends, init schema, onboard agent
# ---------------------------------------------------------------------------
if ($Mode -eq 'infra' -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Warn "docker not found but APP_ENV=infra — falling back to local mode."
  $Mode = 'local'
  ((Get-Content .env -Raw) -replace '(?m)^APP_ENV=.*', 'APP_ENV=local').TrimEnd() + "`n" |
    Set-Content .env -NoNewline
}

if ($Mode -eq 'infra') {
  Log "docker compose up -d (scylla + nats + minio)"
  docker compose up -d

  Log "waiting for ScyllaDB Alternator on :8000 ..."
  $ready = $false
  foreach ($i in 1..60) {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://localhost:8000/ | Out-Null; $ready = $true; break }
    catch { Start-Sleep -Seconds 2 }
  }
  if (-not $ready) { Warn "ScyllaDB did not become ready in time"; exit 1 }

  $env:APP_ENV = 'infra'
  Log "init_infra — create table + GSI + bucket"
  uv run python scripts/init_infra.py
  Log "onboard 401(k) agent as a REST adapter directly into ScyllaDB"
  uv run python scripts/onboard_agent.py
  Log "seed realistic demo lineage (runs + verdicts + batches) for the dashboard"
  uv run python scripts/seed_demo.py
}

# ---------------------------------------------------------------------------
# 4. Run the integrated stack (backend + frontend, one edge) + seed the surfaces
# ---------------------------------------------------------------------------
@"

  Ready.
    mode        : $Mode
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

"@ | Write-Host

if ($NoRun) {
  Log "-NoRun: setup complete."
  Log "  start the stack : uv run python scripts/run_all.py"
  Log "  then seed it    : uv run python scripts/seed_pipeline.py"
  return
}

# Start the whole stack in the background so we can seed the interactive surfaces
# through the real edge once it is live, then hand the console back to the stack.
# SEED_HEAL_INCIDENTS=0 keeps Self-Heal populated only by the real breach detector
# (no hand-written INC-99x incidents); SEED_DEMO (default on) still seeds the
# dashboard/observability rollups + onboards the agent adapter.
Log "starting all services in the background ..."
$env:APP_ENV = $Mode
$env:SEED_HEAL_INCIDENTS = '0'
$proc = Start-Process -FilePath 'uv' -ArgumentList @('run', 'python', 'scripts/run_all.py') `
  -NoNewWindow -PassThru

try {
  Log "waiting for the edge on :8080 ..."
  $edgeUp = $false
  foreach ($i in 1..60) {
    if ($proc.HasExited) { Warn "the stack exited during startup — see the logs above"; exit 1 }
    try {
      Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8080/health | Out-Null
      $edgeUp = $true; break
    } catch { Start-Sleep -Seconds 1 }
  }

  if ($edgeUp) {
    Log "seeding interactive pipeline data (qgen | sim | eval | self-heal) ..."
    try { uv run python scripts/seed_pipeline.py }
    catch { Warn "pipeline seed skipped/failed (stack still up)" }
  } else {
    Warn "edge did not become ready in time — skipping pipeline seed"
  }

  Log "platform ready — http://127.0.0.1:8080/  (Ctrl-C to stop)"
  Wait-Process -Id $proc.Id
}
finally {
  if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}
