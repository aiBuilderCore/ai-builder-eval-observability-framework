/* Self-Heal — closed-loop remediation (mock).

   Synthetic, deterministic seed data — no backend. This screen is analytical:
   it keeps its own seed the same way the observability drift/trajectory screens
   do, and a future `_api.js` adapter can override the SH.incidents seam to
   hydrate from `/self-heal/incidents` without changing the render code.

   Every incident walks the same four-stage closed loop:
     gate (detect) → rca (diagnose) → simulate (rehearse) → remediate (apply)
   governed by a Policy DSL. The loop follows the Arize "closing the loop" model:
   a fix is not "try harder" — it is a missing capability, rehearsed on real
   flagged traces, and submitted WITH evidence (before/after metric vs the gate,
   a confidence score vs the policy band, and a reasoning summary). High-confidence
   fixes auto-ship in-band; the rest escalate to a human who audits the
   self-verification rather than re-reviewing every change. All figures fabricated. */
(function () {
  "use strict";

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  var STAGE_LABEL = { gate: "Gate", rca: "RCA", simulate: "Simulate", remediate: "Remediate" };
  var STAGE_ORDER = ["gate", "rca", "simulate", "remediate"];

  var GLYPH = {
    retriever: '<svg viewBox="0 0 16 16" fill="none"><path d="M8 2.4c3 0 5 .9 5 2v7.2c0 1.1-2 2-5 2s-5-.9-5-2V4.4c0-1.1 2-2 5-2Z" stroke="currentColor" stroke-width="1.2"/><path d="M3 4.4c0 1.1 2 2 5 2s5-.9 5-2M3 8c0 1.1 2 2 5 2s5-.9 5-2" stroke="currentColor" stroke-width="1.2"/></svg>',
    prompt: '<svg viewBox="0 0 16 16" fill="none"><path d="M3 3.4h10a1 1 0 0 1 1 1v5.6a1 1 0 0 1-1 1H7l-3 2.2V11H3a1 1 0 0 1-1-1V4.4a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>',
    tool: '<svg viewBox="0 0 16 16" fill="none"><path d="M9.8 2.6a3 3 0 0 0 3.6 3.6l-2 3.4-3.2 3.2a1.3 1.3 0 0 1-1.8-1.8l3.2-3.2 0.2-5.2Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>',
    parser: '<svg viewBox="0 0 16 16" fill="none"><path d="M6 3 3 8l3 5M10 3l3 5-3 5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    finance: '<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="5.6" stroke="currentColor" stroke-width="1.2"/><path d="M8 5v6M6.4 6.2h2.4a1.2 1.2 0 0 1 0 2.4H6.4h2.6a1.2 1.2 0 0 1 0 2.4H6" stroke="currentColor" stroke-width="1.1" stroke-linecap="round"/></svg>',
    chat: '<svg viewBox="0 0 16 16" fill="none"><path d="M2.6 3.4h10.8a1 1 0 0 1 1 1v5a1 1 0 0 1-1 1H8l-3.2 2.3V10.4H2.6a1 1 0 0 1-1-1v-5a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>',
  };

  // ── Seed incidents ────────────────────────────────────────────────────────
  // status: open (in the loop) · escalated (candidate ready, awaiting human) · resolved (auto-closed + verified)
  var SH = {};
  SH.incidents = [
    {
      id: "INC-992", glyph: "retriever", agent: "RAG Retriever", failure: "Context window overflow",
      pillars: ["Reliability", "Explainability"], stage: "remediate", age: "10 mins ago",
      status: "open", dispo: "Auto-remediating · shipping in-band", dispoClass: "run",
      policy: "rag_quality_v2", band: 0.80, confidence: 0.94, action: "KB update · Re-rank tune",
      timeline: [
        { stage: "gate", status: "done", when: "10 mins ago", note: "Reliability judge fired: 6.1% of retrievals exceeded the 8k-token context budget, breaching the 2% guardrail." },
        { stage: "rca", status: "done", when: "9 mins ago", note: "Root cause traced to an un-chunked knowledge-base upload that pushed average passage length +340%. No re-ranking cap was applied." },
        { stage: "simulate", status: "done", when: "6 mins ago", note: "Shadow-replayed 1,200 flagged sessions with a 512-token chunk cap + top-5 re-rank. Projected overflow 0.3%, quality +2.1 pts, confidence 0.94." },
        { stage: "remediate", status: "active", when: "4 mins ago", note: "0.94 ≥ 0.80 band → auto-shipping in-band. Applied chunking policy v3 and re-indexed; re-measuring the guardrail to confirm close." },
      ],
      fix: {
        change: { before: "chunking: none · re-rank: off · avg passage ≈ 1,700 tok", after: "chunking: 512 tok · re-rank: top-5 (bge-v2) · retriever policy v3" },
        metric: { label: "context-overflow rate", baseline: "6.1%", gate: "≤ 2.0%", projected: "0.3%" },
        quality: "+2.1", sessions: "1,200",
        reasoning: "The fix is a capability the retriever was missing — a chunk cap + re-rank — not a prompt “try harder”. Rehearsed on real flagged traces before shipping.",
      },
      traces: [
        { id: "tr-1030", agent: "Search Agent", intent: "Policy lookup", meta: "3.6s · Planner Drift" },
        { id: "tr-1035", agent: "Finance Extractor", intent: "Invoice reconciliation", meta: "6.1s · Tool Drift" },
      ],
    },
    {
      id: "INC-990", glyph: "finance", agent: "RetireWell 401(k) Planner", failure: "Individualized-advice guardrail breach",
      pillars: ["Safety"], stage: "remediate", age: "35 mins ago",
      status: "escalated", dispo: "Awaiting human review", dispoClass: "warn",
      policy: "finance_guardrail_v1", band: null, confidence: 0.88, action: "Prompt rewrite · Guardrail tweak",
      timeline: [
        { stage: "gate", status: "done", when: "35 mins ago", note: "no_financial_advice judge fired on 2.4% of answers — the assistant named specific funds and a target allocation, breaching the 0.5% guardrail." },
        { stage: "rca", status: "done", when: "28 mins ago", note: "Multi-turn follow-ups inherit the user’s “just tell me what to buy” framing and slip past the educator-not-fiduciary guardrail on turn 3+." },
        { stage: "simulate", status: "done", when: "15 mins ago", note: "Replayed 950 flagged sessions with a hardened follow-up preamble + decline-and-redirect exemplar. Projected breach 0.1%, confidence 0.88." },
        { stage: "remediate", status: "queued", when: "awaiting sign-off", note: "finance_guardrail_v1 is `always open_ticket` — a regulated agent never auto-ships. Routed to #compliance for human approval." },
      ],
      fix: {
        change: { before: "follow-up turns inherit user framing · no decline exemplar", after: "hardened follow-up preamble · decline-and-redirect exemplar · fund-naming + allocation blocked" },
        metric: { label: "no_financial_advice breach", baseline: "2.4%", gate: "≤ 0.5%", projected: "0.1%" },
        quality: "±0", sessions: "950",
        reasoning: "Candidate is strong (0.88), but policy forces human sign-off for this regulated agent — a human audits the self-verification, they don’t re-derive the fix.",
      },
      traces: [
        { id: "tr-1041", agent: "RetireWell 401(k)", intent: "Rollover + allocation", meta: "3.3s · Guardrail breach" },
      ],
    },
    {
      id: "INC-993", glyph: "prompt", agent: "Prompt Template", failure: "Tone regression",
      pillars: ["Transparency", "Fairness"], stage: "simulate", age: "25 mins ago",
      status: "open", dispo: "Rehearsing candidate", dispoClass: "run",
      policy: "client_assist_v3", band: 0.85, confidence: null, action: "Prompt rewrite",
      timeline: [
        { stage: "gate", status: "done", when: "25 mins ago", note: "Tone judge agreement dropped 11% after a prompt edit shipped in release v1.9.2." },
        { stage: "rca", status: "done", when: "22 mins ago", note: "A newly added “be concise” instruction stripped empathetic framing, disproportionately affecting refund and cancellation flows." },
        { stage: "simulate", status: "active", when: "18 mins ago", note: "A/B replaying 800 conversations against the prior template. Awaiting statistical significance before a confidence score is assigned." },
        { stage: "remediate", status: "queued", when: "queued", note: "Pending simulation sign-off. Candidate: restore an empathy preamble scoped to sensitive flows." },
      ],
      fix: {
        change: { before: 'System: "Be concise."', after: 'System: "Be concise, but keep an empathetic opening on refund & cancellation flows."' },
        metric: { label: "tone-judge agreement", baseline: "−11%", gate: "≥ baseline", projected: "measuring…" },
        quality: "tbd", sessions: "800",
        reasoning: "A/B replay in progress; no confidence score until the candidate reaches statistical significance against the prior template.",
      },
      traces: [
        { id: "tr-1036", agent: "Support Agent", intent: "Escalation routing", meta: "4.4s · Planner Drift" },
      ],
    },
    {
      id: "INC-994", glyph: "tool", agent: "Tool Router", failure: "Stuck in infinite loop",
      pillars: ["Reliability", "Safety"], stage: "rca", age: "1 hour ago",
      status: "open", dispo: "Diagnosing · RCA", dispoClass: "idle",
      policy: "client_assist_v3", band: 0.85, confidence: null, action: "Guardrail tweak · Circuit break",
      timeline: [
        { stage: "gate", status: "done", when: "1 hour ago", note: "Trajectory monitor flagged 14 traces exceeding 20 tool calls with zero task progress." },
        { stage: "rca", status: "active", when: "48 mins ago", note: "Investigating a retry cycle between the search and calculator tools when a currency-conversion argument returns null." },
        { stage: "simulate", status: "queued", when: "queued", note: "Blocked on RCA. Proposed guard: cap tool-call depth at 8 and short-circuit null-argument retries." },
        { stage: "remediate", status: "queued", when: "queued", note: "Not started." },
      ],
      fix: null,
      traces: [
        { id: "tr-1029", agent: "Support Agent", intent: "Refund processing", meta: "4.2s · Tool Drift" },
        { id: "tr-1032", agent: "Support Agent", intent: "Account cancellation", meta: "5.1s · Tool Drift" },
      ],
    },
    {
      id: "INC-995", glyph: "parser", agent: "Output Parser", failure: "JSON schema violation",
      pillars: ["Reliability"], stage: "gate", age: "2 hours ago",
      status: "open", dispo: "Triaging · gate", dispoClass: "idle",
      policy: null, band: null, confidence: null, action: "Fall-back",
      timeline: [
        { stage: "gate", status: "active", when: "2 hours ago", note: "Schema-validation judge rejected 3.8% of outputs (missing required “confidence” field), above the 1% gate." },
        { stage: "rca", status: "queued", when: "queued", note: "Queued. Preliminary signal points to a model version bump changing default field ordering." },
        { stage: "simulate", status: "queued", when: "queued", note: "Not started." },
        { stage: "remediate", status: "queued", when: "queued", note: "Not started." },
      ],
      fix: null,
      traces: [
        { id: "tr-1033", agent: "Code Copilot", intent: "PR review synthesis", meta: "5.0s · Schema violation" },
      ],
    },
    {
      id: "INC-988", glyph: "chat", agent: "Support Agent", failure: "Refund-policy hallucination",
      pillars: ["Reliability", "Safety"], stage: "remediate", age: "3 hours ago",
      status: "resolved", dispo: "Auto-resolved · verified", dispoClass: "ok",
      policy: "client_assist_v3", band: 0.85, confidence: 0.91, action: "Prompt rewrite · KB update",
      timeline: [
        { stage: "gate", status: "done", when: "3 hours ago", note: "Hallucination judge fired: 4.0% of refund answers cited a non-existent 30-day window, above the 1% guardrail." },
        { stage: "rca", status: "done", when: "2h 58m ago", note: "Attributed to a stale KB snippet plus a prompt that never required citing the policy source span." },
        { stage: "simulate", status: "done", when: "2h 50m ago", note: "Replayed 1,500 flagged sessions with a refreshed KB + cite-the-source instruction. Projected hallucination 0.2%, confidence 0.91." },
        { stage: "remediate", status: "done", when: "2h 44m ago", note: "0.91 ≥ 0.85 band → shipped in-band. Re-measured the guardrail: 0.2% over the next 1,500 live sessions. Incident auto-closed." },
      ],
      fix: {
        change: { before: "KB: refund-policy v2 (stale) · prompt: no source-cite requirement", after: "KB: refund-policy v4 · prompt: “cite the policy source span for any time window”" },
        metric: { label: "hallucination rate", baseline: "4.0%", gate: "≤ 1.0%", projected: "0.2%" },
        quality: "+1.4", sessions: "1,500", verified: "0.2% over 1,500 post-ship sessions",
        reasoning: "Missing capability: nothing required the agent to ground time-window claims in a cited span. Fix added the capability + refreshed the source, then verified on live traffic.",
      },
      traces: [
        { id: "tr-1021", agent: "Support Agent", intent: "Refund window query", meta: "2.9s · Hallucination" },
      ],
    },
  ];

  SH.registry = [
    "Prompt rewrite", "Re-rank tune", "Guardrail tweak", "Fall-back", "KB update", "Circuit break",
  ];

  // Policy DSL — declarative auto-remediation. Rendered read-only with light
  // token highlighting; `.k` keyword, `.s` string, `.n` number.
  SH.policies = [
    {
      name: "client_assist_v3",
      lines: [
        ['<span class="k">policy</span> <span class="s">"client_assist_v3"</span> {'],
        ['  <span class="k">on</span> hallucination_rate &gt; <span class="n">0.10</span> <span class="k">from</span> support_agent'],
        ['  <span class="k">diagnose with</span> rca_agent <span class="k">and</span> simulate'],
        ['  <span class="k">if</span> confidence &gt;= <span class="n">0.85</span> <span class="k">then</span> ship_fix'],
        ['  <span class="k">else</span> open_ticket <span class="k">and</span> notify <span class="s">"#ai-quality"</span>'],
        ["}"],
      ],
    },
    {
      name: "rag_quality_v2",
      lines: [
        ['<span class="k">policy</span> <span class="s">"rag_quality_v2"</span> {'],
        ['  <span class="k">on</span> context_overflow_rate &gt; <span class="n">0.02</span> <span class="k">from</span> knowledge_search'],
        ['  <span class="k">diagnose with</span> rca_agent <span class="k">and</span> simulate'],
        ['  <span class="k">if</span> confidence &gt;= <span class="n">0.80</span> <span class="k">then</span> apply(<span class="s">"re-rank tune"</span>)'],
        ['  <span class="k">else</span> escalate'],
        ["}"],
      ],
    },
    {
      name: "finance_guardrail_v1",
      lines: [
        ['<span class="k">policy</span> <span class="s">"finance_guardrail_v1"</span> {'],
        ['  <span class="k">on</span> no_financial_advice_breach &gt; <span class="n">0.005</span> <span class="k">from</span> retirement_401k'],
        ['  <span class="k">diagnose with</span> rca_agent <span class="k">and</span> simulate'],
        ['  <span class="k">always</span> open_ticket <span class="k">and</span> notify <span class="s">"#compliance"</span>'],
        ["}"],
      ],
    },
  ];

  // ── Render helpers ──────────────────────────────────────────────────────────
  function stageChip(stage) {
    return '<span class="chip stage-badge stage-badge--' + stage + '">' + esc(STAGE_LABEL[stage]) + "</span>";
  }
  function dispoChip(inc) {
    return '<span class="chip chip--' + inc.dispoClass + '">' + esc(inc.dispo) + "</span>";
  }

  function renderKpis() {
    // Prefer the live /self-heal/summary rollup when the adapter has set it;
    // otherwise derive from the local seed so the page reads offline too.
    var s = SH.summary;
    var open = s ? s.open_incidents
      : SH.incidents.filter(function (i) { return i.status !== "resolved"; }).length;
    document.getElementById("kpi-open").textContent = open;
    document.getElementById("kpi-auto").textContent = s ? s.auto_resolved_24h : "12";
    document.getElementById("kpi-mttr").textContent = s ? s.median_mttr : "18m";
    document.getElementById("kpi-policies").textContent = s ? s.active_policies : SH.policies.length;
  }

  // ── Queue with filter ───────────────────────────────────────────────────────
  var FILTERS = [
    { id: "all",      label: "All",             test: function () { return true; } },
    { id: "open",     label: "In progress",     test: function (i) { return i.status === "open"; } },
    { id: "escalated",label: "Awaiting review", test: function (i) { return i.status === "escalated"; } },
    { id: "resolved", label: "Resolved",        test: function (i) { return i.status === "resolved"; } },
  ];
  var activeFilter = "all";

  function renderFilter() {
    var host = document.getElementById("queue-filter");
    if (!host) return;
    host.innerHTML = FILTERS.map(function (f) {
      var n = SH.incidents.filter(f.test).length;
      return (
        '<button type="button" class="sh-pill' + (f.id === activeFilter ? " is-active" : "") + '" data-filter="' + f.id + '">' +
        esc(f.label) + ' <span class="sh-pill__n">' + n + "</span></button>"
      );
    }).join("");
  }

  function renderQueue() {
    var host = document.getElementById("queue");
    var filter = FILTERS.filter(function (f) { return f.id === activeFilter; })[0] || FILTERS[0];
    var rows = SH.incidents.filter(filter.test);
    host.innerHTML = rows.map(function (inc) {
      var conf = inc.confidence != null ? " · conf " + inc.confidence.toFixed(2) : "";
      return (
        '<button type="button" class="incident" data-inc="' + esc(inc.id) + '">' +
        '  <span class="incident__icon" aria-hidden="true">' + (GLYPH[inc.glyph] || "") + "</span>" +
        '  <span class="incident__main">' +
        '    <span class="incident__id">' + esc(inc.id) + "</span>" +
        '    <p class="incident__title">' + esc(inc.agent) + "</p>" +
        '    <p class="incident__failure">' + esc(inc.failure) + "</p>" +
        '    <span class="incident__dispo dispo--' + inc.dispoClass + '">' + esc(inc.dispo) + esc(conf) + "</span>" +
        '    <span class="incident__tags">' +
        inc.pillars.map(function (p) { return '<span class="tag">' + esc(p) + "</span>"; }).join("") +
        "    </span>" +
        "  </span>" +
        '  <span class="incident__right">' +
        stageChip(inc.stage) +
        '    <span class="incident__time">' + esc(inc.age) + "</span>" +
        "  </span>" +
        "</button>"
      );
    }).join("");
    document.getElementById("queue-count").textContent = rows.length + " shown";
  }

  function renderRegistry() {
    document.getElementById("registry").innerHTML = SH.registry
      .map(function (a) { return '<span class="tag">' + esc(a) + "</span>"; })
      .join("");
  }

  function renderPolicies() {
    document.getElementById("policies").innerHTML = SH.policies
      .map(function (p) {
        return (
          '<p class="dsl__name">' + esc(p.name) + "</p>" +
          '<pre class="dsl">' + p.lines.map(function (l) { return l[0]; }).join("\n") + "</pre>"
        );
      })
      .join("");
  }

  // ── Incident modal ─────────────────────────────────────────────────────────
  var modal = document.getElementById("modal");
  var dialog = document.getElementById("modal-dialog");

  function tlItem(step) {
    var cls = step.status === "done" ? "tl__item--done" : step.status === "active" ? "tl__item--active" : "";
    var mark = step.status === "done" ? "✓" : step.status === "active" ? "⟳" : STAGE_ORDER.indexOf(step.stage) + 1;
    var statusChip =
      step.status === "done" ? '<span class="chip chip--ok">complete</span>' :
      step.status === "active" ? '<span class="chip chip--run">in progress</span>' :
      '<span class="chip chip--idle">queued</span>';
    return (
      '<li class="tl__item ' + cls + '">' +
      '  <span class="tl__rail"><span class="tl__dot">' + mark + "</span></span>" +
      '  <span class="tl__content">' +
      '    <span class="tl__head"><span class="tl__stage">' + esc(STAGE_LABEL[step.stage]) + "</span>" +
      statusChip +
      '      <span class="tl__when">' + esc(step.when) + "</span></span>" +
      '    <p class="tl__note">' + esc(step.note) + "</p>" +
      "  </span>" +
      "</li>"
    );
  }

  function confMeter(inc) {
    if (inc.confidence == null) {
      return '<p class="conf__note">Confidence pending — assigned once the candidate reaches statistical significance in simulation.</p>';
    }
    var pct = Math.round(inc.confidence * 100);
    var ship = inc.band != null && inc.confidence >= inc.band;
    var fill = ship ? "var(--ok)" : "var(--warn)";
    var band = inc.band != null ? '<span class="conf__band" style="left:' + (inc.band * 100) + '%"></span>' : "";
    var note = inc.band == null
      ? "Policy <b>" + esc(inc.policy) + "</b>: <b>always open ticket</b> → human review required regardless of score."
      : (ship
          ? "Confidence <b>" + inc.confidence.toFixed(2) + "</b> ≥ band <b>" + inc.band.toFixed(2) + "</b> under <b>" + esc(inc.policy) + "</b> → auto-ship in-band."
          : "Confidence <b>" + inc.confidence.toFixed(2) + "</b> &lt; band <b>" + inc.band.toFixed(2) + "</b> under <b>" + esc(inc.policy) + "</b> → escalate out-of-band.");
    return (
      '<div class="conf">' +
      '  <div class="conf__track">' +
      '    <span class="conf__fill" style="width:' + pct + "%;background:" + fill + '"></span>' + band +
      "  </div>" +
      '  <p class="conf__note">' + note + "</p>" +
      "</div>"
    );
  }

  function verdictBlock(inc) {
    if (inc.status === "escalated") {
      return (
        '<div class="sh-actions">' +
        '  <button class="btn btn--primary" type="button" data-act="approve">Approve &amp; ship</button>' +
        '  <button class="btn" type="button" data-act="ticket">Send to ticket</button>' +
        '  <button class="btn" type="button" data-act="reject">Reject fix</button>' +
        "</div>" +
        '<div class="sh-verdict sh-verdict--warn">Human-in-the-loop: you’re auditing the self-verification (the traces, evidence, and confidence) — not re-deriving the fix.</div>'
      );
    }
    if (inc.status === "resolved") {
      return '<div class="sh-verdict sh-verdict--ok">✓ <span>Verified &amp; auto-closed — post-ship metric <b>' + esc(inc.fix.verified) + "</b>. The guardrail re-measure confirms the fix held.</span></div>";
    }
    if (inc.stage === "remediate") {
      return '<div class="sh-verdict sh-verdict--run">⟳ <span>Auto-remediating — shipping in-band and re-measuring the guardrail to confirm the loop closes.</span></div>';
    }
    return '<div class="sh-verdict sh-verdict--run">⟳ <span>Rehearsing the candidate in the simulated practice world — no ship until it clears the policy band.</span></div>';
  }

  function fixPanel(inc) {
    if (!inc.fix) {
      return (
        '<p class="sh-eyebrow" style="margin-top:1.4rem;">Candidate fix &amp; evidence</p>' +
        '<p class="sh-reason">No candidate yet — pending ' + esc(STAGE_LABEL[inc.stage]) +
        " diagnosis. The RCA agent must attribute a cause class + span path before a fix is rehearsed and scored.</p>"
      );
    }
    var f = inc.fix;
    return (
      '<p class="sh-eyebrow" style="margin-top:1.4rem;">Candidate fix &amp; evidence</p>' +
      '<div class="fixdiff">' +
      '  <div class="fixdiff__row fixdiff__row--before"><span class="fixdiff__mark">−</span>' + esc(f.change.before) + "</div>" +
      '  <div class="fixdiff__row fixdiff__row--after"><span class="fixdiff__mark">+</span>' + esc(f.change.after) + "</div>" +
      "</div>" +
      '<div class="sh-evi">' +
      '  <div class="sh-evi__cell"><div class="sh-evi__k">' + esc(f.metric.label) + '</div><div class="sh-evi__v">' + esc(f.metric.baseline) + ' <em>vs ' + esc(f.metric.gate) + " gate</em></div></div>" +
      '  <div class="sh-evi__cell"><div class="sh-evi__k">projected</div><div class="sh-evi__v" style="color:var(--ok)">' + esc(f.metric.projected) + "</div></div>" +
      '  <div class="sh-evi__cell"><div class="sh-evi__k">quality Δ</div><div class="sh-evi__v">' + esc(f.quality) + ' <em>pts</em></div></div>' +
      "</div>" +
      '<p class="conf__note">Evidence: <b>' + esc(f.sessions) + "</b> flagged sessions shadow-replayed against the candidate on real traces.</p>" +
      confMeter(inc) +
      '<p class="sh-reason">' + esc(f.reasoning) + "</p>" +
      verdictBlock(inc)
    );
  }

  function openIncident(id) {
    var inc = SH.incidents.filter(function (i) { return i.id === id; })[0];
    if (!inc) return;
    dialog.innerHTML =
      '<div class="sh-modal__head">' +
      '  <div class="sh-modal__titles">' +
      '    <h2 class="sh-modal__title" id="modal-title">' + esc(inc.agent) + " " + dispoChip(inc) + "</h2>" +
      '    <p class="sh-modal__sub">Closed-loop remediation trace · ' + esc(inc.failure.toLowerCase()) + ".</p>" +
      "  </div>" +
      '  <button class="sh-modal__x" type="button" data-close aria-label="Close">×</button>' +
      "</div>" +
      '<div class="sh-modal__body">' +
      '  <div class="sh-summary">' +
      '    <div class="sh-summary__row"><span class="sh-summary__id">' + esc(inc.id) + "</span>" +
      '      <span class="sh-summary__time">' + esc(inc.age) + "</span></div>" +
      '    <p class="sh-summary__agent">' + esc(inc.agent) + "</p>" +
      '    <p class="sh-summary__failure">' + esc(inc.failure) + "</p>" +
      '    <span class="incident__tags">' +
      inc.pillars.map(function (p) { return '<span class="tag">' + esc(p) + "</span>"; }).join("") +
      "    </span>" +
      "  </div>" +
      '  <p class="sh-eyebrow">Closed-loop progress</p>' +
      '  <ul class="tl">' + inc.timeline.map(tlItem).join("") + "</ul>" +
      fixPanel(inc) +
      '  <p class="sh-eyebrow" style="margin-top:1.4rem;">Remediation action · registry</p>' +
      '  <div class="sh-registry">' +
      inc.action.split(" · ").map(function (a) { return '<span class="tag">' + esc(a) + "</span>"; }).join("") +
      "  </div>" +
      '  <p class="sh-eyebrow" style="margin-top:1.4rem;">Related traces · ' + inc.traces.length + " flagged</p>" +
      inc.traces.map(function (t) {
        return (
          '<a class="sh-trace" href="../observability/trace.html?id=' + encodeURIComponent(t.id) + '">' +
          '  <span class="sh-trace__id">' + esc(t.id) + "</span>" +
          '  <span class="sh-trace__agent">' + esc(t.agent) + " · " + esc(t.intent) + "</span>" +
          '  <span class="sh-trace__meta">' + esc(t.meta) + "</span>" +
          "</a>"
        );
      }).join("") +
      "</div>";
    dialog.setAttribute("data-inc", inc.id);
    modal.hidden = false;
    modal.classList.add("is-open");
    document.body.style.overflow = "hidden";
    if (history.replaceState) history.replaceState(null, "", "#" + inc.id);
  }

  function closeModal() {
    modal.classList.remove("is-open");
    modal.hidden = true;
    document.body.style.overflow = "";
    if (history.replaceState) history.replaceState(null, "", location.pathname + location.search);
  }

  var ACT_MSG = {
    approve: "Mock: candidate fix approved & shipped in-band. In the wired version this promotes the fix and re-measures the guardrail to confirm the incident closes.",
    ticket: "Mock: routed to an out-of-band ticket (e.g. #compliance). The incident stays open until a human ships or rejects the fix.",
    reject: "Mock: candidate fix rejected. RCA re-opens to propose an alternative from the remediation registry.",
  };

  // ── Wire ───────────────────────────────────────────────────────────────────
  document.getElementById("queue").addEventListener("click", function (e) {
    var btn = e.target.closest("[data-inc]");
    if (btn) openIncident(btn.getAttribute("data-inc"));
  });
  var filterHost = document.getElementById("queue-filter");
  if (filterHost) filterHost.addEventListener("click", function (e) {
    var b = e.target.closest("[data-filter]");
    if (!b) return;
    activeFilter = b.getAttribute("data-filter");
    renderFilter();
    renderQueue();
  });
  modal.addEventListener("click", function (e) {
    if (e.target === modal || e.target.closest("[data-close]")) { closeModal(); return; }
    var act = e.target.closest("[data-act]");
    if (!act) return;
    var kind = act.getAttribute("data-act");
    var incId = dialog.getAttribute("data-inc");
    // A live adapter (SH.onAction) POSTs the human verdict to the edge; without
    // it we fall back to the descriptive mock alert.
    if (typeof SH.onAction === "function") { SH.onAction(incId, kind); return; }
    window.alert(ACT_MSG[kind] || "Mock action.");
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && modal.classList.contains("is-open")) closeModal();
  });
  document.getElementById("new-policy").addEventListener("click", function () {
    window.alert("New-policy authoring is stubbed in the mock — policies are read-only here.");
  });

  function renderAll() {
    renderKpis();
    renderFilter();
    renderQueue();
    renderRegistry();
    renderPolicies();
  }

  renderAll();

  // Deep link: /self-heal/#INC-992 opens that incident (parity with the
  // "View remediation →" links from the trajectory/trace screens).
  var hash = (location.hash || "").replace(/^#/, "");
  if (hash) openIncident(hash);

  // Expose the data + render seam so the LIVE adapter below can hydrate from the
  // edge and repaint without duplicating any render code.
  SH.renderAll = renderAll;
  SH.openIncident = openIncident;
  SH.closeModal = closeModal;
  SH.isOpen = function () { return modal.classList.contains("is-open"); };
  window.SH = SH;
})();

// ── LIVE wiring ──────────────────────────────────────────────────────────────
// When the API Orchestration edge is reachable, hydrate the Self-Heal seam from
// /self-heal/* and route the human-in-the-loop verdicts to the real endpoints.
// Follows the repo recipe: guard on window.EEOF, map API → the app's UI shapes
// (the only rename is dispo_class → dispoClass), override the SH.* seam, repaint.
(function () {
  if (!window.EEOF || !window.SH) return;
  var SH = window.SH;

  function mapIncident(i) {
    // API shape ≈ UI shape; normalise the one snake_case field + policy DSL lines.
    i.dispoClass = i.dispo_class;
    return i;
  }
  function mapPolicy(p) {
    // The DSL renderer expects `lines` as [[html]]; the API returns `dsl` as [html].
    return { name: p.name, lines: (p.dsl || []).map(function (l) { return [l]; }) };
  }

  var poll = null;

  async function hydrate() {
    if (!(await EEOF.isLive())) return; // offline → keep the bundled seed
    try {
      var res = await Promise.all([
        EEOF.get("/self-heal/incidents"),
        EEOF.get("/self-heal/policies"),
        EEOF.get("/self-heal/registry"),
        EEOF.get("/self-heal/summary"),
      ]);
      SH.incidents = (res[0] || []).map(mapIncident);
      SH.policies = (res[1] || []).map(mapPolicy);
      SH.registry = (res[2] || []).map(function (a) { return a.name; });
      SH.summary = res[3] || null;
      // Don't repaint over an open modal mid-read; refresh the list underneath.
      if (!SH.isOpen()) SH.renderAll();
      else { SH.renderAll(); }
    } catch (e) { /* transient edge blip — keep last good render */ }
  }

  // Human verdict → live endpoint. approve ships async (202 + job); the poll
  // picks up the resolved incident. ticket/reject mutate synchronously.
  SH.onAction = async function (incId, kind) {
    try {
      await EEOF.post("/self-heal/incidents/" + encodeURIComponent(incId) + "/action", {
        action: kind,
      });
    } catch (e) {
      window.alert("Action failed against the edge: " + e.message);
      return;
    }
    SH.closeModal();
    await hydrate();
  };

  hydrate();
  poll = setInterval(hydrate, 5000);
  window.addEventListener("beforeunload", function () { if (poll) clearInterval(poll); });
})();
