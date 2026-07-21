# Self-Heal / RCA — Work Stack

Living backlog for the Self-Heal stage (`frontend-web/self-heal/*`) and its
service (`services/self-heal-svc/*`, `packages/core/.../self_heal_detect.py`).
Ordered top-of-stack first. **The user adds points on the go — append under the
matching track and keep IDs stable.**

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[?]` needs decision

> **Session 2026-07-21:** A0–A7, B1–B4, C1, D1 (backend), E1 all landed and verified
> in-browser against a live run (`scripts/self_heal_demo.py`). Full suite green
> (29 passed), ruff clean. Only remaining: **D1 UI** (policy picker in the
> Evaluation wizard — backend seam is complete and driveable via the API).

---

## Track A — RCA view polish (the incident modal)

- [x] **A0 · Pillar tags render as grey boxes.** In Self-Heal `.tag` only gets the
  shared chrome rule (border + `surface-alt` bg, no padding/radius, `display:block`)
  — reads as a square grey box, worst on the accent-soft summary card.
  → Fixed in `self-heal/styles.css`: scoped `.incident__tags .tag` to a
  borderless soft-accent pill. (Hard-reload to clear CSS cache.)

- [x] **A1 · Render the guardrail diff, don't ask the user to imagine it. (was P1)**
  `hydrateDiagnosis` (`app.js:265`) fetches only the flagged trace. Also fetch a
  passing baseline trace and show the system-prompt **diff** (reuse the existing
  `.fixdiff` before/after component). This is a *guardrail-regression* story — show
  the regression. Highest value.

- [x] **A2 · Show attribution, not just evidence. (was P2)** Panel is titled "what
  the agent saw" but never states a cause class / span path, despite the pipeline
  card promising it (`index.html:75`). Add a one-line attribution
  (cause class · failing span · `score < threshold`) pulled from the verdict.
  Feeds Track C (policy-driven RCA).

- [x] **A3 · Kill the stub content that reads as unfinished. (was P3)**
  - Completion + user turn are echo-provider stubs ("Okay, that helps." / "Short
    version: yes — do X…").
  - Model label leaks the provider chain: `MODEL FALLBACK(GROQ → ECHO)`
    (rendered verbatim from `gen_ai.request.model`, `app.js:289`) — clean it to
    the resolved model name.
  - Judge rationale in the RCA timeline note is `"Deterministic offline judge
    verdict (echo)."` (`self_heal_detect.py:146`) — suppress/replace when running
    on echo instead of quoting an empty rationale.

- [x] **A4 · Mark the completion as the failure. (was P4)** The three "what the
  agent saw" boxes are visually identical; the completion is the thing that
  breached — give it an error/warn tint (mirror `.fixdiff` red language).
  `.sh-diag__v` in `self-heal/styles.css`.

- [x] **A5 · Cut modal-head redundancy. (was P5)** Agent name appears 3× (title,
  summary card, block); RCA stage stated 4×. The `.sh-summary` card (`app.js:314`)
  duplicates the header — collapse and reclaim vertical space.

- [x] **A6 · Modal scroll + focus. (was P6)** Give the dialog its own scroll region
  with a sticky header (related-traces list currently cut at the fold, saw 2 of 3).
  Move focus into the dialog on open + trap it — `openIncident` (`app.js:352`) sets
  `aria-modal` but never focuses.

- [x] **A7 · Simulator loop card shows a junk glyph.** `index.html:82`
  `<p class="stage__reuse">↺ reuses Persona Lab · Question Gen · Simulation</p>`
  — the `↺` (U+21BA) renders as mojibake/tofu. Replace with a clean inline SVG
  recycle/loop icon (match the `GLYPH` SVG set in `app.js:29`) or a supported glyph.

---

## Track B — Policy ↔ judge alignment & wiring

- [x] **B1 · Policies don't cover the judges that actually fire.** Incidents match a
  policy by *substring* of the breached judge name in `trigger`
  (`self_heal_detect.py:85 _match_policy`). The 3 seed policies
  (`self-heal-svc/.../seed.py:23`) only resolve `hallucination` and
  `no_financial_advice`; `context_overflow_rate` maps to **no judge**. Result: ~14
  of 16 judges open incidents with `policy=None, band=None` → the modal confidence
  meter has no band. Add policies covering the real judge set
  (`judge_catalog.py:CORE_JUDGES`), keyed to judge `name`/`dimension`, so every
  breach that can fire has a governing policy. Decide the canonical trigger vocab
  (judge-name vs. metric-name like `_rate`/`_breach`).

- [x] **B2 · `from <agent>` scope in triggers is ignored.** `_match_policy` only
  substring-matches the dimension and never checks the agent clause, so a
  `client_assist_v3` policy scoped "from support_agent" matches a breach from any
  agent. Make matching structured (dimension + agent + comparator + threshold)
  instead of `dim in trigger`.

- [x] **B3 · New-policy authoring (was a stub alert).** "＋ New policy" now opens a
  real authoring form (name · governed-judge picker · agent scope · escalate-vs-
  auto-ship band · notify) → `POST /self-heal/policies` (edge-proxied) → `PolicyDraft`
  → `build_policy` renders the DSL (author text HTML-escaped) → persisted via
  `save_policy` → list + KPI refresh. Server validates (name/dimensions required,
  band 0–1, duplicate → 409); the form surfaces the edge's message (drilling through
  the proxy's nested `detail`). The new policy immediately governs matching breaches
  (structured B1/B2 matching). Verified end-to-end in-browser.

---

## Track C — Policy-driven RCA (good RCA content from policies)

- [x] **C1 · Synthesize RCA from the governing policy.** Today the RCA note is just
  the raw (often stub) judge rationale. Derive a richer, real diagnosis by combining
  breached judge + its threshold + matched policy (band, ship-vs-escalate intent,
  notify channel, proposed registry action). e.g. *"Governed by
  `finance_guardrail_v1` → always escalate to #compliance; `no_financial_advice`
  (Safety, thr 0.90) breached at X%; proposed: Guardrail tweak · Prompt rewrite."*
  Deterministic and real — no fabrication. Surface it in the RCA panel (ties to A2)
  and the `rca` timeline step (`self_heal_detect.py:173`).

---

## Track D — Apply a policy to a specific run

- [~] **D1 · Bind a policy at run-submit time.** No mechanism attaches a policy to
  an evaluation run today (policies are global, matched post-hoc). Design:
  (a) structured policy scope (judge/dimension + agent + band) — depends on B1/B2;
  (b) freeze a policy ref into the eval job envelope at submit (per the "immutable
  snapshot" edge rule in CLAUDE.md);
  (c) `detect_incidents` reads the frozen policy ref instead of substring-scanning;
  (d) UI to pick/show the governing policy on the run (Evaluation submit + run
  detail), and show it on the incident. `[?]` auto-bind by agent vs. explicit pick.

---

## Track F — Agent-side remediation recommendation (trace-grounded)

- [x] **F1 · "What to fix on the agent" recommendation.** The modal only showed an
  abstract registry *category* (e.g. "Guardrail tweak"), not a concrete agent-side
  fix. Added `eeof_core/self_heal_playbook.py` — a per-judge remediation catalog
  (surface · summary · trace-evidence · steps · recommended prompt fix · reference),
  served at `GET /self-heal/playbook` (edge-proxied) and rendered in the RCA panel.
- [x] **F2 · Evidence & incorrect-prompt highlight come from the TRACE, not code.**
  Self-Heal has only the trace (OTel/OpenInference spans), never the agent's source.
  So: the offending clauses are highlighted verbatim **in the real captured system
  prompt** (`mark.sh-flag`, driven by playbook `flags`), and the recommendation's
  "incorrect" side is the exact clause **extracted from the trace's PROMPT span**;
  the fix is a recommended prompt-clause replacement. No fabricated code — behaviour
  dimensions (numeric_accuracy, tool_call_correctness, …) describe the trace signal
  (missing tool span, retry loop) and recommend changes, with no diff/highlight.
  `[?]` extra evidence (e.g. tool-arg deltas) can be surfaced by enriching the OTel
  spans upstream, then read here — no code access required.

## Track E — KPIs

- [x] **E1 · Median MTTR is blank / faked.** `store.summary` (`store.py:126`) returns
  a hardcoded `_MEDIAN_MTTR = "18m"` and only when resolved incidents exist,
  otherwise `"—"` (currently blank — no resolved incidents). Compute it for real
  from resolved incidents' `opened_at → resolved_at` durations (median), and ensure
  `resolved_at` is stamped on auto-close/approve. Frontend already reads
  `summary.median_mttr` (`app.js:64`) — just needs a real value.

---

## Sequencing note
B1+B2 unblock C1 and D1; A2 and C1 share the attribution surface. Suggested order:
**A0 (done) → A7/A3 (quick wins) → B1/B2 → C1 → A1/A2 → D1 → E1 → A4/A5/A6.**
