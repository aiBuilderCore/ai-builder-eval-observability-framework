# Observability Enhancement — Gap Analysis & Remediation Plan

**Scope:** Observability stage and its upstream dependencies (Simulation, Evaluation),
across all seven tabs — Live, Batches, Calibration, Trajectory, Datasets, Gate, Evidence.
**Method:** Live Playwright scan of `http://127.0.0.1:8080/observability/*` against the
running `local` stack (real seeded pipeline: 2 batches, 8 runs), cross-checked against
the frontend wiring (`frontend-web/observability/`), the edge (`api-orchestration`),
`observability-svc`, and the shared rollups in `packages/core`.
**Date:** 2026-07-14 · **Branch:** `fix/observability-patching`

---

## 1. Executive summary

The observability surface is **~60% genuinely wired** and **~40% seed/fabricated or
structurally underpowered**. The parts that read real pipeline data (batches, verdicts,
quality/spend rollups, calibration records, gate decisions, evidence packs) work and are
honest. But four categories of problems undercut the demo's credibility:

| # | Theme | Severity |
|---|-------|----------|
| A | **No telemetry substrate.** There is zero OpenTelemetry / OpenInference instrumentation anywhere in the codebase. Every "span" surface is empty or seed. The Live page advertises "OTLP/gRPC 4317" that does not exist. | **P0** |
| B | **Real signals not surfaced; seed shown instead.** The Live "Recent incidents" list is hardcoded seed while the real breach incidents (self-heal store) are never read. The index hero counts "judge verdicts" from the empty spans array, so it shows `~0` despite 20 real verdicts. | **P0** |
| C | **Structurally incomplete features.** Gate has no real baseline→candidate comparison (baseline always `—`). Datasets is a client-only scratchpad with no backend. Trajectory is honestly-labeled seed. | **P1** |
| D | **Data-quality / provenance drift.** Judge scores fall back to `echo` (rate-limited groq) yet still report `model: groq:llama-3.3-70b-versatile`; calibration reads κ=1.00 everywhere (an echo artifact, not a real agreement signal). | **P1** |

The single highest-leverage fix — and the one that unlocks Trajectory, batch span-trees,
the SPAN/TRAJECTORY monitor kinds, and meaningful traces — is **instrumenting the
agent-under-test with real OpenTelemetry + OpenInference spans and carrying them through
simulation → ingest → store**. This is Section 6, and it is the answer to "do we need to
create complete OTel trace/span at the agent side": **yes.**

---

## 2. How the data actually flows today

```
agent-under-test  POST /chat {messages} -> {reply}      (black box, no spans)
        │
simulation-svc    drives turn-by-turn, records a TRACE blob = {turns[], annotations{}}
        │         annotations.tool_calls_made is always 0 (agent makes no tool calls)
        │         emits trace.events.<run_id> -> folded into a Batch aggregate (traces, tokens)
        │
evaluation-svc    per trace×judge -> VERDICT {score, passed, judge_ref, rationale}
        │         writes CALIBRATION record per judge (κ vs gold)
        │
observability-svc read API: /batches /monitors /incidents /gate /evidence /calibration
        │         + rollups: /quality /spend  (aggregate real verdict/token/count rows)
        │
frontend          hydrate() stitches batches × runs × verdicts × traces × verdict-sets
                  × gate client-side; overrides State.* seams (app.js:866-1121)
```

Key structural fact: **the trace blob is a conversation transcript, not a span tree.**
There are no LLM / TOOL / RETRIEVER / CHAIN spans anywhere. Anything in the UI that
implies span geometry is therefore either empty or seed.

Evidence (trace blob shape, `.eeof-blobs/traces/.../*.json`):
```json
{ "turns": [{ "role":"user"|"agent", "text", "latency_ms", "tokens":{"in","out"} }],
  "annotations": { "tool_calls_made": 0, "tool_call_failures": 0, "topic_drift_max": 0.35 } }
```

---

## 3. Tab-by-tab findings

### Index / hero (`index.html`)
- **Real:** batches (2), runs (8), Recent-batches table, pass-rate, lineage — all live.
- 🐛 **Bug:** the hero "spans" and "judge verdicts" pills are computed from `r.spans`
  (`index.html:203-204`), which `buildRuns()` hard-sets to `[]` (`app.js:933`). Result:
  **"~0 judge verdicts" while 20 real verdicts exist.** `pill-eval` should count
  `r.verdicts`, not EVALUATOR spans.
- ⚠️ **"~0 spans"** is defensible only because there is no span source (Section 6).

### 1 · Live (`monitors.html`)
- **Real:** authored-monitors list (empty — none created), SPAN/SCORE/TRAJECTORY/ANOMALY
  kind tiles (0 each), the create-monitor wizard (POSTs a real `MonitorDraft`).
- 🚩 **Seed surfacing:** "Recent incidents" shows **hardcoded** `inc_01HXC2P9`
  (Adversarial Aaron), `inc_01HXC2QA` (billing agent), `inc_01HXC2QB` (faithfulness_v3),
  all "68d ago." `hydrate()` (`app.js:1011-1019`) **never fetches `/observability/incidents`.**
- 🔌 **Disconnect:** `/observability/incidents` returns `[]` because it queries the
  observability incidents GSI, but the real breach incidents are written to the **self-heal**
  store (`keys.heal_incident_pk`, see `rollups.py:127`). The 2 real breaches from
  `seed_pipeline` are invisible here.
- ⚠️ **Fabricated monitor fields:** even when a monitor exists, `mapMonitor` (`app.js:971-981`)
  hardcodes `sparkline: [0.3,0.32,…]`, `trend:"flat"`, `fires_30d:0`, `last_fired:null`,
  `routing:["slack:#eval-alerts"]`, `severity:"warn"`, `window:"5m/1m"`, `cohort`. Monitors
  never actually evaluate against live data — the "state advances every ~30s" is a
  client-side animation.
- ❌ **Fiction:** the OTLP/gRPC 4317 / OTLP/HTTP 4318 ingest endpoints do not exist.

### 2 · Batches (`index.html` + `batches.js`, detail `batch.html`)
- **Real:** batch list, per-trace runs, verdicts, transcript, pass-rate, 4-tuple lineage.
- ⚠️ **Span histogram degenerate:** `kind_histogram` only ever contains
  `{ EVALUATOR: <verdict count> }` (`app.js:952,966`). The LLM/TOOL/RETRIEVER geometry a
  real batch-detail span view would show is absent.
- 🐛 **Denominator mismatch:** batch pass-rate is trace-based (3/4 = 75%) while the same
  run's gate/verdict-set pass-rate is verdict-based (7/8 = 87.5%). The two numbers describe
  the same run and will confuse users; pick one denominator or label both.

### 3 · Calibration (`calibration.html`)
- **Real & well-wired:** 5 judges, live `/observability/calibration` records, sample sizes.
- ⚠️ **Meaningless values:** κ=1.00 and agreement=100% for **every** judge — an artifact of
  the echo provider producing deterministic scores, so inter-rater agreement is trivially
  perfect. Not a real trust signal.
- ⚠️ **Fabricated framing:** `kappa_target:0.75`, `kappa_threshold:0.65`, `window_days:30`
  are hardcoded (`app.js:1100-1103`); `series:[c.kappa]` is a single point — the "30-day
  rolling window" and trend chart are aspirational ("single sample · no rolling trend yet").

### 4 · Trajectory (`trajectory.html`)
- ✅ **Honestly labeled** "illustrative · no backend telemetry source." Batch pickers are
  wired to real runs; heatmap / distribution-diff / delegation graph are seed.
- ⚠️ **Persona mismatch:** the heatmap rows are seed personas (Adversarial Aaron, Methodical
  Mei…) while the real runs use "First-Timer Femi." Reinforces that nothing here is this
  run's data. Blocked entirely on Section 6 (needs per-span tool/plan/delegation telemetry).

### 5 · Datasets (`datasets.html`)
- 🚩 **No backend at all** — labeled "local scratchpad · no backend store." `State.datasets()`
  starts `[]` (`app.js:1091`); promote/health/export are pure client state, lost on reload.
- 🔌 **Dead links:** "promote → dataset" from incidents (`datasets.html?from_incident=…`) and
  the promote wizard write nothing durable. The entire Curate stage is non-functional beyond
  a mockup. No edge routes, no `dataset` entity, no keys.

### 6 · Gate (`gate.html`)
- **Real:** gate decisions per verdict set (2 evaluated, 1 blocked, 1 passed) via
  `/observability/gate/{candidate}`; four-tuple "what changed" diff.
- ⚠️ **No real comparison:** `evaluate_gate` (`store.py:88-101`) is a **single-set threshold
  check** (`pass_rate >= 0.8`). Baseline is always `null` (`app.js:996,1000`) → the signal
  table shows `baseline: —`, `Δ: —`. The headline promise ("two batches head-to-head,
  baseline vs candidate") is not delivered.
- ⚠️ **Decorative signals:** only `pass_rate` is ever checked. "FAITHFULNESS MIN ≥ 80",
  "trajectory drift z-score" thresholds are shown but never evaluated.

### 7 · Evidence (`packs.html`)
- **Real:** 1 assembled pack (`ev_…`), async assembly worker, gate-pinned, blob-backed.
- ⚠️ **Fabricated pack metadata:** `mapPack` (`app.js:982-988`) hardcodes `issued_by:"system"`,
  `time_range:"—"`, `monitors:0`, `incidents:0`, `pages:1`.
- ⚠️ **Decorative wizard:** template (EU AI Act / SR 11-7 / NYC AEDT / FINRA), tenant
  (finrobot/globex/hireright), and time-range (2026-Q1…) selectors don't scope the request —
  `savePacks` (`app.js:1075-1088`) always posts `candidate = batchesCache[0]` with its verdict
  set, ignoring the selected scope.

---

## 4. Simulation traces & evaluation output — underutilization

The upstream stages produce richer data than observability consumes:

**Simulation traces carry, but observability drops:**
- `stop_reason` (`topic_drift`, `goal_met`, `max_turns`) — a real per-run failure signal, not
  surfaced in the batch/run tables.
- `annotations` (`topic_drift_max`, `longest_assistant_silence_ms`, `tool_calls_made`) —
  never displayed; these are the closest thing to trajectory signal that exists today.
- per-turn `latency_ms` / `tokens` — aggregated into a single `duration_ms`/`tokens_total`,
  never shown as a per-turn timeline.

**Evaluation verdicts carry, but observability drops or misreports:**
- `rationale` — real field, but currently "Deterministic offline judge verdict (echo)"
  because of the groq rate-limit fallback; not shown in the run view.
- `consensus_rate` — `null` **and this is correct, not a gap.** Only one LLM is wired in this
  deployment, so a multi-model jury cannot run; `worker.py:114` correctly leaves
  `consensus_rate` null outside `mode in {panel,jury}` with n>1. **Action is UI-side:** hide
  or disable the jury/consensus affordance while a single provider is wired, rather than
  showing an empty column that implies missing data. Re-enable it automatically once a second
  judge model is configured. Do **not** fabricate a consensus value.
- `mitigations_applied` (`position_swap`, `length_normalization`), `scored_turns`,
  `pillar` (empty on the verdict; rollup recovers it via `JUDGE_PILLARS`) — all unused in the
  observability surface.
- **Provenance bug:** the verdict's `judges[].model` reports `groq:llama-3.3-70b-versatile`
  even though the score came from the echo fallback. Any "which model judged this" display is
  wrong. Provenance should reflect the *resolved* provider link, not the configured primary.

---

## 5. Backend wiring gaps (summary table)

| Surface | Edge route exists? | Real data? | Gap |
|---------|:---:|:---:|-----|
| Batches / runs / verdicts | ✅ | ✅ | span geometry absent (Section 6) |
| Quality / Spend rollups | ✅ | ✅ | none — genuinely derived |
| Calibration | ✅ | ✅ | κ meaningless under echo; no rolling series |
| Monitors (list/create) | ✅ | partial | no evaluation loop; monitors never fire |
| Incidents | ✅ | ❌ | route reads empty obs GSI; real breaches in self-heal store; UI shows seed |
| Gate | ✅ | partial | single-set threshold; no baseline comparison; only pass_rate |
| Evidence | ✅ | ✅ | pack metadata hardcoded; wizard scope ignored |
| Datasets | ❌ | ❌ | no entity, no keys, no route — client scratchpad only |
| Trajectory | ❌ | ❌ | no per-span telemetry source |
| OTLP ingest (4317/4318) | ❌ | ❌ | advertised, does not exist |

---

## 6. The core fix — real OpenTelemetry / OpenInference spans at the agent

**Answer to the open question:** yes — to make spans meaningful we must emit a complete
OTel trace at the agent side (OpenInference semantic conventions), carry the trace through
simulation, ingest the spans in observability, and store them. Today the agent is a single
`/chat → {reply}` black box (`agent-under-test/app.py`) with no instrumentation, so every
span surface (batch span-tree, trajectory drift, SPAN/TRAJECTORY monitors, the hero "spans"
pill) has nothing to read.

### 6.1 Make the agent-under-test actually agentic + instrumented
Right now the 401(k) agent does one LLM call and returns text — there are no tools to trace.
To produce a meaningful span tree it needs (a) real steps and (b) OTel instrumentation:

1. **Add dependencies:** `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`,
   `openinference-semantic-conventions` (workspace `llm`/`infra` group).
2. **Give the agent tools** so a trace has shape — e.g. `contribution_calculator`,
   `irs_limit_lookup` (retrieval), `risk_profiler`. Wrap the `/chat` handler in a CHAIN span;
   each LLM call an `LLM` span with `llm.model_name`, `llm.token_count.{prompt,completion}`,
   `llm.invocation_parameters`; each tool call a `TOOL` span with `tool.name`,
   `tool.parameters`, `output.value`; retrieval a `RETRIEVER` span with `retrieval.documents`.
3. **Set OpenInference attributes** (`openinference.span.kind` = `CHAIN|LLM|TOOL|RETRIEVER|AGENT`)
   so downstream consumers get a typed span tree, not just OTel generic spans.
4. **Propagate trace context** from the simulation adapter (`traceparent` header on `/chat`)
   so all of a run's spans share one trace id and can be stitched to the simulation trace.

### 6.2 Capture spans through simulation → ingest → store
1. **Simulation adapter** (`simulation-svc/adapters.py`) collects the agent's exported spans
   (either the agent returns them in the `/chat` response envelope, or exports OTLP to a
   collector the sim reads) and attaches them to the trace blob alongside `turns`.
2. **Span contract in core** — add a `Span` model (`packages/core/.../models/`) with the
   OpenInference fields; store spans in the trace blob and/or a `SPAN#` key range.
3. **Ingest** — extend `record_trace_event` (`observability-svc/store.py:32`) to fold real
   span kinds into `Batch.kind_histogram` (LLM/TOOL/RETRIEVER/EVALUATOR counts) and per-kind
   latency/cost, instead of only incrementing `traces`/`tokens`.
4. **Frontend** — `buildRuns` (`app.js:894-936`) stops hard-setting `spans:[]` and maps the
   real spans; batch-detail span-tree and the hero pills light up automatically.

### 6.3 What this unblocks
- Batch-detail **span tree** and a real `kind_histogram`.
- **Trajectory** tab (tool-call edit distance, planner-step KL, delegation graph) gets its
  telemetry source and stops being seed.
- Monitor kinds **SPAN** (latency/cost/token budget) and **TRAJECTORY** become evaluable.
- The index **"spans"** pill becomes a real number.

> Note: even after 6.1–6.2, some analytical views (24h heatmaps, multi-window drift) need
> *volume* of production traffic. For the demo, seed a modest span history so the visuals
> render — but drive them from the same `Span` contract, not a separate seed shape.

---

## 7. Prioritized remediation plan

### P0 — correctness & honesty (small, high-impact)
1. **Index hero:** count judge verdicts from `r.verdicts`, not `r.spans` (`index.html:203-210`).
2. **Live incidents:** fetch `/observability/incidents` in `hydrate()` and render real rows;
   delete the hardcoded seed incidents. Decide whether the observability incidents route
   should union the self-heal breach store (it currently reads an empty GSI).
3. **Judge provenance:** report the *resolved* provider on `judges[].model` (echo when the
   fallback fired), so calibration/verdict provenance isn't misleading.
4. **Remove or gate fiction:** either implement OTLP ingest or stop advertising 4317/4318 and
   the "advances every ~30s" monitor animation as if it were live.
5. **Jury/consensus UI:** hide or disable the jury/consensus column while only one LLM is
   wired (single-provider deployment — jury is intentionally unavailable), so an empty column
   doesn't read as missing data. Auto-enable when a second judge model is configured.

### P1 — structural completeness
6. **Gate:** implement real baseline→candidate comparison in `evaluate_gate` (accept a
   `baseline` param, compute per-signal deltas); wire the baseline picker. Evaluate the
   signals actually shown (faithfulness, trajectory z-score) or remove them.
7. **Calibration:** persist a rolling κ series (append per evaluation run) so the trend chart
   is real; source target/threshold from judge config, not hardcode.
8. **Monitors:** add a real evaluation loop (a monitor worker that scores live/batch data
   against thresholds and opens incidents) so monitors fire; derive sparkline/fires_30d/
   last_fired from those firings.
9. **Datasets:** add a `dataset` entity + keys + edge routes (`POST /observability/datasets`,
   promote-from-run, export). Until then, relabel promote/export as non-persistent.

### P2 — the telemetry substrate (Section 6)
10. Instrument agent-under-test with OTel + OpenInference; add real tools.
11. Define the `Span` contract; capture through simulation; ingest real span kinds; drop the
    `spans:[]` stub. Unblocks Trajectory + span-trees + SPAN/TRAJECTORY monitors.

### P1 — provenance/data-quality enabler
12. Fix the groq rate-limit fallback (real key / backoff / different judge model) so verdict
    scores, rationales, and κ stop being echo artifacts — this makes Calibration and the
    quality rollups *meaningful*, not just *present*.

---

## 8. Fabricated / mock data inventory (what to hunt down)

| Location | Fabricated |
|----------|-----------|
| `monitors.html` "Recent incidents" | 3 hardcoded seed incidents (`inc_01HXC2…`, "68d ago") |
| `app.js:971-981` `mapMonitor` | sparkline, trend, fires_30d, last_fired, routing, severity, window, cohort |
| `app.js:982-988` `mapPack` | issued_by, time_range, monitors, incidents, pages |
| `app.js:1100-1103` calibration | kappa_target, kappa_threshold, window_days, single-point series |
| `app.js:996-1006` `mapGate` | baseline_batch/baseline/delta all null |
| `trajectory.html` | heatmap, distribution diff, delegation graph, seed personas |
| `packs.html` wizard | template/tenant/time-range selectors (don't scope the request) |
| `datasets.html` | entire tab — client scratchpad, no persistence |
| `monitors.html` | OTLP 4317/4318 endpoints, "advances every ~30s" |
| verdict `judges[].model` | reports groq while echo actually scored |

---

## 9. Suggested sequencing

1. **Day 1 (P0 1–4):** honesty pass — hero count, real incidents, provenance, drop/park
   fiction. Cheap, immediately makes the demo trustworthy.
2. **Day 2–3 (P1 5–8, 11):** gate comparison, calibration series, monitor firing loop,
   datasets backend, groq fallback fix.
3. **Week 2 (P2 9–10):** OTel/OpenInference substrate — the durable unlock for Trajectory,
   span-trees, and span/trajectory monitors.
