/* Self Heal — closed-loop remediation.

   No bundled data. Every incident, policy, and KPI is hydrated live from the
   `/self-heal/*` edge by the LIVE-wiring adapter at the bottom of this file;
   when the edge is unreachable the screen renders honest empty states rather
   than mock data. Incidents are OPENED by the real pipeline — the evaluation
   worker's breach detector (`eeof_core.self_heal_detect`) writes one whenever a
   judge fails its guardrail on a real run.

   Every incident walks the same four-stage closed loop:
     gate (detect) → rca (diagnose) → simulate (rehearse) → remediate (apply)
   governed by a Policy DSL. The loop follows the Arize "closing the loop" model:
   a fix is a missing capability rehearsed on real flagged traces and submitted
   WITH evidence. Detection is automated; the RCA/simulate/ship agents are not
   in this build, so a freshly-detected incident sits at RCA with its fix panel
   honestly "pending" until a human triages it. */
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

  // ── Live seams (populated by the LIVE-wiring adapter below) ─────────────────
  // status: open (in the loop) · escalated (candidate ready, awaiting human) · resolved (auto-closed + verified)
  // Registry + policies are built-in config served unconditionally by the edge;
  // incidents are earned by real breaches. All start empty — no bundled mock.
  var SH = {};
  SH.incidents = [];
  SH.registry = [];
  SH.policies = [];
  SH.playbook = {};  // dimension → agent-side remediation recommendation

  // Highlight the offending phrases (from the playbook) inside the real captured
  // system prompt — showcases the exact incorrect prompt text that caused the breach.
  function highlightFlags(text, flags) {
    var safe = esc(text || "");
    (flags || []).forEach(function (f) {
      if (!f) return;
      var ef = esc(f).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      try {
        safe = safe.replace(new RegExp(ef, "gi"), function (m) {
          return '<mark class="sh-flag">' + m + "</mark>";
        });
      } catch (e) { /* bad pattern → leave text as-is */ }
    });
    return safe;
  }

  // ── Render helpers ──────────────────────────────────────────────────────────
  function stageChip(stage) {
    return '<span class="chip stage-badge stage-badge--' + stage + '">' + esc(STAGE_LABEL[stage]) + "</span>";
  }
  function dispoChip(inc) {
    return '<span class="chip chip--' + inc.dispoClass + '">' + esc(inc.dispo) + "</span>";
  }

  // C1 · one-line governance summary — which policy governs this incident and what
  // it will do (auto-ship vs. escalate). Derived from the incident's policy + band.
  function governanceLine(inc) {
    if (!inc.policy) {
      return '<p class="sh-gov sh-gov--none"><span class="sh-gov__k">policy</span>' +
        "No governing policy — manual triage until one is bound.</p>";
    }
    var intent = inc.band == null
      ? "always escalate for human sign-off"
      : "auto-ship at confidence ≥ " + inc.band.toFixed(2) + ", else escalate";
    return '<p class="sh-gov"><span class="sh-gov__k">policy</span>' +
      "<b>" + esc(inc.policy) + "</b> → " + esc(intent) + "</p>";
  }

  function renderKpis() {
    // Prefer the live /self-heal/summary rollup; otherwise derive strictly from
    // whatever incidents/policies are loaded (empty ⇒ 0 / "—"). Never fabricate.
    var s = SH.summary;
    var open = s ? s.open_incidents
      : SH.incidents.filter(function (i) { return i.status !== "resolved"; }).length;
    var resolved = SH.incidents.filter(function (i) { return i.status === "resolved"; }).length;
    document.getElementById("kpi-open").textContent = open;
    document.getElementById("kpi-auto").textContent = s ? s.auto_resolved_24h : resolved;
    document.getElementById("kpi-mttr").textContent = s ? s.median_mttr : "—";
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
    if (!rows.length) {
      host.innerHTML =
        '<div class="sh-empty">' +
        '  <p class="sh-empty__title">No open incidents — the loop is clear.</p>' +
        '  <p class="sh-empty__sub">Incidents open automatically when a judge fails its guardrail on a real evaluation run. Drive a run (or <code>scripts/self_heal_demo.py</code>) to see one here.</p>' +
        "</div>";
      document.getElementById("queue-count").textContent = "0 shown";
      return;
    }
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
    document.getElementById("registry").innerHTML = SH.registry.length
      ? SH.registry.map(function (a) { return '<span class="tag">' + esc(a) + "</span>"; }).join("")
      : '<span class="sh-empty__sub">Loading the remediation registry from the edge…</span>';
  }

  function policyMode(p) {
    if (p.always_ticket) return { cls: "warn", label: "always escalate" };
    if (p.band != null) return { cls: "ok", label: "auto-ship ≥ " + p.band.toFixed(2) };
    return { cls: "idle", label: "escalate" };
  }

  function renderPolicies() {
    if (!SH.policies.length) {
      document.getElementById("policies").innerHTML =
        '<span class="sh-empty__sub">Loading policies from the edge…</span>';
      return;
    }
    document.getElementById("policies").innerHTML = SH.policies.map(function (p) {
      var mode = policyMode(p);
      var dims = (p.dimensions || []).map(function (d) {
        return '<span class="pol__judge">' + esc(d) + "</span>";
      }).join("");
      var meta = [];
      meta.push("agent " + (p.agent ? esc(p.agent) + "*" : "any"));
      if (p.notify) meta.push("notify " + esc(p.notify));
      return (
        '<div class="pol">' +
        '  <div class="pol__head">' +
        '    <span class="pol__name">' + esc(p.name) + "</span>" +
        '    <span class="pol__mode pol__mode--' + mode.cls + '">' + esc(mode.label) + "</span>" +
        "  </div>" +
        (dims ? '<div class="pol__judges">' + dims + "</div>" : "") +
        '  <p class="pol__meta">' + meta.join(" · ") + "</p>" +
        '  <details class="pol__src"><summary>Policy DSL</summary>' +
        '<pre class="dsl">' + p.lines.map(function (l) { return l[0]; }).join("\n") + "</pre></details>" +
        "</div>"
      );
    }).join("");
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
    if (inc.fix && inc.stage === "remediate") {
      return '<div class="sh-verdict sh-verdict--run">⟳ <span>Auto-remediating — shipping in-band and re-measuring the guardrail to confirm the loop closes.</span></div>';
    }
    if (inc.fix && inc.stage === "simulate") {
      return '<div class="sh-verdict sh-verdict--run">⟳ <span>Rehearsing the candidate in the simulated practice world — no ship until it clears the policy band.</span></div>';
    }
    // Detect-only: the breach was detected on real traces, but the RCA/simulate/
    // ship agents are not automated in this build — say so honestly.
    return '<div class="sh-verdict sh-verdict--run">◔ <span>Detected on real flagged traces. RCA attribution, candidate rehearsal, and ship are not automated in this build — a human triages from the evidence here.</span></div>';
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

  function pickSpan(spans, kind) {
    for (var i = 0; i < spans.length; i++) if (spans[i].kind === kind) return spans[i];
    return null;
  }

  // The last user turn as the model actually saw it — read from the LLM span's
  // captured input messages, falling back to the transcript.
  function lastUserMessage(llmAttrs, detail) {
    var bestIdx = -1;
    Object.keys(llmAttrs || {}).forEach(function (k) {
      var m = /^llm\.input_messages\.(\d+)\.message\.role$/.exec(k);
      if (m && llmAttrs[k] === "user" && +m[1] > bestIdx) bestIdx = +m[1];
    });
    if (bestIdx >= 0) return llmAttrs["llm.input_messages." + bestIdx + ".message.content"] || "";
    var turns = ((detail && detail.turns) || []).filter(function (t) { return t.role === "user"; });
    return turns.length ? turns[turns.length - 1].text : "";
  }

  // Clean a captured model label for display. The provider layer records the
  // fallback CHAIN (e.g. "fallback(groq → echo)") on the span; a reviewer wants
  // the model the agent effectively ran under — the last live link — not the
  // internal chain string. Flag echo as offline so a generic completion reads honestly.
  function cleanModel(raw) {
    if (!raw) return { label: "—", offline: false };
    var m = String(raw);
    var inner = /^fallback\((.*)\)$/i.exec(m.trim());
    if (inner) m = inner[1];
    var links = m.split(/→|->|,/).map(function (s) { return s.trim(); }).filter(Boolean);
    var eff = links.length ? links[links.length - 1] : m.trim();
    var offline = /echo/i.test(eff);
    return { label: eff, offline: offline };
  }

  // Pull the system prompt / user turn / completion off a trace's OpenInference
  // PROMPT+LLM spans — the verbatim record of what the agent ran under.
  function readAgentView(detail) {
    var spans = (detail && detail.spans) || [];
    var prompt = pickSpan(spans, "PROMPT"), llm = pickSpan(spans, "LLM");
    if (!prompt && !llm) return null;
    var pa = (prompt && prompt.attrs) || {}, la = (llm && llm.attrs) || {};
    var view = {
      system: pa["input.value"] || la["llm.system"] || "",
      completion: la["output.value"] || la["llm.output_messages.0.message.content"] || "",
      user: lastUserMessage(la, detail),
      model: cleanModel(la["gen_ai.request.model"]),
      params: la["llm.invocation_parameters"] || "",
      spanKinds: spans.map(function (s) { return s.kind; }),
    };
    if (!view.system && !view.completion && !view.user) return null;
    return view;
  }

  // Recommended agent-side fix — trace-grounded (we have only the trace, not the
  // agent's code). For prompt-fixable dimensions the "incorrect" side is the exact
  // offending clause EXTRACTED FROM the trace's PROMPT span, and the recommendation
  // is a prompt-clause replacement. Behaviour dimensions describe the trace signal
  // and recommend changes — never fabricated code.
  function recSection(rec, view, tid) {
    if (!rec || !rec.summary) return "";
    var offending = [];
    (rec.flags || []).forEach(function (f) {
      var re;
      try { re = new RegExp(f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"); } catch (e) { return; }
      var m = re.exec(view.system || "");
      if (m) offending.push(m[0]);
    });
    var diff = "";
    if (offending.length && rec.fix) {
      diff =
        '<div class="sh-rec__snip sh-diag--diff">' +
        '<span class="sh-diag__k">Prompt clause · from trace ' +
        '<span class="sh-diagnosis__trace">' + esc(tid) + " · PROMPT span</span> → recommended</span>" +
        '<div class="fixdiff">' +
        '  <div class="fixdiff__row fixdiff__row--before"><span class="fixdiff__mark">from trace</span>' + esc(offending.join("  …  ")) + "</div>" +
        '  <div class="fixdiff__row fixdiff__row--after"><span class="fixdiff__mark">recommend</span>' + esc(rec.fix) + "</div>" +
        "</div></div>";
    }
    return (
      '<p class="sh-eyebrow" style="margin-top:1.4rem;">Recommended fix · agent side' +
      (rec.surface ? ' <span class="sh-rec__surface">' + esc(rec.surface) + "</span>" : "") + "</p>" +
      '<p class="sh-rec__summary">' + esc(rec.summary) + "</p>" +
      (rec.evidence ? '<p class="sh-rec__evi"><span class="sh-rec__evi-k">evidence</span>' + esc(rec.evidence) + "</p>" : "") +
      diff +
      '<ol class="sh-rec__steps">' +
      (rec.steps || []).map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") +
      "</ol>" +
      (rec.reference ? '<p class="sh-rec__ref">Satisfies <b>' + esc(rec.reference) + "</b></p>" : "")
    );
  }

  // RCA diagnosis: lazily pull the exemplar flagged trace and surface *exactly*
  // what the agent ran under — the verbatim system prompt (guardrails in effect),
  // the user prompt, and the completion — captured on the trace's OpenInference
  // PROMPT/LLM spans. When the run produced a PASSING trace for the same judge, we
  // also fetch it and contrast the two completions (A1) — a real good-vs-flagged
  // diff, not a fabricated baseline. Above it, a one-line attribution (A2).
  function hydrateDiagnosis(inc) {
    var host = document.getElementById("sh-diagnosis");
    if (!host) return;
    if (!window.EEOF || !inc.traces || !inc.traces.length) return; // seed/offline → stay hidden
    var tid = inc.traces[0].id;
    var flaggedMeta = inc.traces[0].meta || "";
    var baseId = inc.baseline_trace && inc.baseline_trace.id;
    var rec = (SH.playbook && SH.playbook[inc.dimension]) || {};
    var flags = rec.flags || [];
    host.hidden = false;
    host.innerHTML =
      '<p class="sh-eyebrow" style="margin-top:1.4rem;">RCA · what the agent saw</p>' +
      '<p class="sh-diagnosis__loading">Loading the flagged trace…</p>';

    var jobs = [EEOF.get("/simulation/traces/" + encodeURIComponent(tid))];
    if (baseId) jobs.push(EEOF.get("/simulation/traces/" + encodeURIComponent(baseId)).catch(function () { return null; }));

    Promise.all(jobs).then(function (res) {
      var view = readAgentView(res[0]);
      if (!view) { host.hidden = true; return; }
      var base = res[1] ? readAgentView(res[1]) : null;

      // A2 · attribution headline — cause class (pillar), breached judge, the
      // failing span the breach was produced on, and the real failing score.
      var pillar = (inc.pillars && inc.pillars[0]) || "Reliability";
      var dim = inc.failure.replace(/ guardrail breach$/, "");
      var failSpan = view.spanKinds.indexOf("LLM") >= 0 ? "LLM span" :
        (view.spanKinds.indexOf("PROMPT") >= 0 ? "PROMPT span" : "agent span");
      var scoreM = /score\s+([0-9.]+)/.exec(flaggedMeta);
      var scoreTxt = scoreM ? "judge score " + scoreM[1] + " (below gate)" : "judge guardrail breached";
      var modelTag = esc(view.model.label) + (view.model.offline ? ' <em class="sh-diag__off">offline</em>' : "");

      var html =
        '<p class="sh-eyebrow" style="margin-top:1.4rem;">RCA · what the agent saw ' +
        '<span class="sh-diagnosis__trace">' + esc(tid) + "</span></p>" +
        '<div class="sh-attr">' +
        '  <span class="sh-attr__k">cause class</span><span class="sh-attr__v">' + esc(pillar) + "</span>" +
        '  <span class="sh-attr__k">judge</span><span class="sh-attr__v">' + esc(dim) + "</span>" +
        '  <span class="sh-attr__k">span</span><span class="sh-attr__v">' + failSpan + "</span>" +
        '  <span class="sh-attr__k">signal</span><span class="sh-attr__v">' + esc(scoreTxt) + "</span>" +
        "</div>" +
        '<div class="sh-diagnosis__grid">' +
        '  <div class="sh-diag"><span class="sh-diag__k">System prompt in effect · model ' + modelTag +
        '</span><pre class="sh-diag__v sh-diag__v--prompt">' + (view.system ? highlightFlags(view.system, flags) : "(not captured)") + "</pre></div>" +
        '  <div class="sh-diag"><span class="sh-diag__k">User prompt</span>' +
        '<pre class="sh-diag__v">' + esc(view.user || "(not captured)") + "</pre></div>";

      // A1 · per-judge completion contrast when a real passing trace exists.
      // Framed strictly by THIS judge's verdict (failed vs. passed), not good-vs-bad:
      // passing one judge is not the same as a better answer overall.
      if (base && base.completion) {
        html +=
          '  <div class="sh-diag sh-diag--diff">' +
          '<span class="sh-diag__k">Completion · this judge — failed vs. passed <span class="sh-diagnosis__trace">' + esc(baseId) + "</span></span>" +
          '<div class="fixdiff">' +
          '  <div class="fixdiff__row fixdiff__row--before"><span class="fixdiff__mark">failed</span>' + esc(view.completion || "(not captured)") + "</div>" +
          '  <div class="fixdiff__row fixdiff__row--after"><span class="fixdiff__mark">passed</span>' + esc(base.completion) + "</div>" +
          "</div></div>";
      } else {
        html +=
          '  <div class="sh-diag"><span class="sh-diag__k">Agent completion · flagged</span>' +
          '<pre class="sh-diag__v sh-diag__v--bad">' + esc(view.completion || "(not captured)") + "</pre></div>";
      }

      html += "</div>" +
        '<p class="sh-diagnosis__hint">Captured verbatim from the flagged trace’s OpenInference LLM span' +
        (view.params ? " (" + esc(view.params) + ")" : "") +
        (base ? ". Both rows are real traces from this run: the top failed <b>" + esc(dim) + "</b>, the bottom passed it. The contrast is per-judge — a pass here is not necessarily a better answer overall (other guardrails may still flag it)."
              : ". Compare the guardrail text above against a passing trace to attribute the breach.") + "</p>";
      html += recSection(rec, view, tid);
      host.innerHTML = html;
    }).catch(function () { host.hidden = true; });
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
      '    <span class="incident__tags">' +
      inc.pillars.map(function (p) { return '<span class="tag">' + esc(p) + "</span>"; }).join("") +
      "    </span>" +
      governanceLine(inc) +
      "  </div>" +
      '  <p class="sh-eyebrow">Closed-loop progress</p>' +
      '  <ul class="tl">' + inc.timeline.map(tlItem).join("") + "</ul>" +
      '  <div class="sh-diagnosis" id="sh-diagnosis" hidden></div>' +
      fixPanel(inc) +
      '  <p class="sh-eyebrow" style="margin-top:1.4rem;">' +
      (inc.status === "resolved" ? "Remediation action · applied"
        : inc.stage === "remediate" ? "Remediation action · shipping"
        : "Remediation action · proposed") + "</p>" +
      '  <div class="sh-registry">' +
      (inc.action
        ? inc.action.split(" · ").map(function (a) { return '<span class="tag">' + esc(a) + "</span>"; }).join("")
        : '<span class="sh-empty__sub">No action selected yet — the RCA agent picks one from the registry once it attributes the root cause.</span>') +
      "  </div>" +
      (inc.action && inc.status !== "resolved" && inc.stage !== "remediate"
        ? '<p class="conf__note">Candidate drawn from the registry for a <b>' + esc(inc.failure) +
          "</b> — confirmed and applied only after RCA and a policy-band clearance.</p>"
        : "") +
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
    lastFocused = document.activeElement;
    modal.hidden = false;
    modal.classList.add("is-open");
    document.body.style.overflow = "hidden";
    if (history.replaceState) history.replaceState(null, "", "#" + inc.id);
    hydrateDiagnosis(inc);
    // Move focus into the dialog so keyboard/SR users aren't stranded behind the backdrop.
    var first = dialog.querySelector("[data-close]");
    if (first) first.focus();
  }

  var lastFocused = null;

  function closeModal() {
    modal.classList.remove("is-open");
    modal.hidden = true;
    document.body.style.overflow = "";
    if (history.replaceState) history.replaceState(null, "", location.pathname + location.search);
    if (lastFocused && lastFocused.focus) lastFocused.focus();
    lastFocused = null;
  }

  // Keep Tab focus inside the open dialog.
  function trapFocus(e) {
    if (e.key !== "Tab" || !modal.classList.contains("is-open")) return;
    var f = dialog.querySelectorAll('a[href],button:not([disabled]),[tabindex]:not([tabindex="-1"])');
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
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
    else trapFocus(e);
  });
  document.getElementById("new-policy").addEventListener("click", function () {
    if (typeof SH.createPolicy === "function") openPolicyForm();
    else window.alert("New-policy authoring needs the live edge — it's read-only offline.");
  });

  // ── New-policy authoring form ────────────────────────────────────────────────
  function openPolicyForm() {
    var dims = Object.keys(SH.playbook || {});
    if (!dims.length) {
      dims = [
        "helpfulness", "faithfulness", "answer_relevance", "hallucination",
        "refusal_correctness", "coherence_multiturn", "role_adherence",
        "factual_consistency", "toxicity", "tool_call_correctness",
        "no_financial_advice", "regulatory_disclosure", "numeric_accuracy",
        "pii_leakage", "demographic_fairness",
      ];
    }
    var overlay = document.createElement("div");
    overlay.className = "sh-modal is-open";
    overlay.id = "policy-modal";
    overlay.innerHTML =
      '<div class="sh-modal__dialog sh-modal__dialog--form" role="dialog" aria-modal="true" aria-label="New policy">' +
      '  <div class="sh-modal__head">' +
      '    <div class="sh-modal__titles"><h2 class="sh-modal__title">New policy</h2>' +
      '      <p class="sh-modal__sub">Govern which breaches auto-ship vs. escalate.</p></div>' +
      '    <button class="sh-modal__x" type="button" data-pclose aria-label="Close">×</button>' +
      "  </div>" +
      '  <div class="sh-modal__body">' +
      '    <form id="pform" novalidate>' +
      '      <label class="pf__l" for="pf-name">Name</label>' +
      '      <input class="pf__i" id="pf-name" name="name" autocomplete="off" placeholder="e.g. safety_gate_v1" />' +
      '      <label class="pf__l">Governed judges</label>' +
      '      <div class="pf__judges">' +
      dims.map(function (d) {
        return '<label class="pf__chk"><input type="checkbox" name="dim" value="' + esc(d) + '"> ' + esc(d) + "</label>";
      }).join("") +
      "      </div>" +
      '      <label class="pf__l" for="pf-agent">Agent scope <span class="pf__opt">optional</span></label>' +
      '      <input class="pf__i" id="pf-agent" name="agent" autocomplete="off" placeholder="any agent — or a fragment like “retire”" />' +
      '      <label class="pf__l">Decision</label>' +
      '      <div class="pf__modes">' +
      '        <label class="pf__radio"><input type="radio" name="mode" value="escalate" checked> Always escalate <span class="pf__hint">human sign-off</span></label>' +
      '        <label class="pf__radio"><input type="radio" name="mode" value="ship"> Auto-ship at confidence ≥ <input type="number" name="band" class="pf__num" min="0" max="1" step="0.01" value="0.85" disabled></label>' +
      "      </div>" +
      '      <label class="pf__l" for="pf-notify">Notify channel</label>' +
      '      <input class="pf__i" id="pf-notify" name="notify" autocomplete="off" placeholder="#ai-quality" />' +
      '      <p class="pf__err" id="pf-err" hidden></p>' +
      '      <div class="sh-actions">' +
      '        <button type="submit" class="btn btn--primary">Create policy</button>' +
      '        <button type="button" class="btn" data-pclose>Cancel</button>' +
      "      </div>" +
      "    </form>" +
      "  </div>" +
      "</div>";
    document.body.appendChild(overlay);
    document.body.style.overflow = "hidden";
    var form = overlay.querySelector("#pform");
    var errEl = overlay.querySelector("#pf-err");
    var bandInput = overlay.querySelector('input[name="band"]');
    var nameInput = overlay.querySelector("#pf-name");
    if (nameInput) nameInput.focus();

    function close() {
      overlay.remove();
      if (!modal.classList.contains("is-open")) document.body.style.overflow = "";
    }
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay || e.target.closest("[data-pclose]")) close();
    });
    overlay.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
    overlay.querySelectorAll('input[name="mode"]').forEach(function (r) {
      r.addEventListener("change", function () {
        bandInput.disabled = overlay.querySelector('input[name="mode"]:checked').value !== "ship";
      });
    });
    function fail(msg) { errEl.textContent = msg; errEl.hidden = false; }
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var name = form.name.value.trim();
      var dimsSel = Array.prototype.slice
        .call(form.querySelectorAll('input[name="dim"]:checked'))
        .map(function (c) { return c.value; });
      var mode = form.querySelector('input[name="mode"]:checked').value;
      if (!name) return fail("Give the policy a name.");
      if (!dimsSel.length) return fail("Select at least one judge to govern.");
      var band = null, alwaysTicket = true;
      if (mode === "ship") {
        band = parseFloat(form.band.value);
        alwaysTicket = false;
        if (isNaN(band) || band < 0 || band > 1) return fail("Confidence band must be between 0 and 1.");
      }
      errEl.hidden = true;
      var btn = form.querySelector('button[type="submit"]');
      btn.disabled = true; btn.textContent = "Creating…";
      SH.createPolicy({
        name: name, dimensions: dimsSel, agent: form.agent.value.trim() || null,
        band: band, always_ticket: alwaysTicket, notify: form.notify.value.trim(),
      }).then(close).catch(function (err) {
        btn.disabled = false; btn.textContent = "Create policy";
        fail((err && err.message) || "Create failed against the edge.");
      });
    });
  }

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
// When the API Orchestration edge is reachable, hydrate the Self Heal seam from
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
    // Structured scope (dimensions/agent/band/…) drives the refined policy card.
    return {
      name: p.name,
      lines: (p.dsl || []).map(function (l) { return [l]; }),
      dimensions: p.dimensions || [],
      agent: p.agent || null,
      band: (p.band === undefined ? null : p.band),
      always_ticket: !!p.always_ticket,
      notify: p.notify || "",
      trigger: p.trigger || "",
    };
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
        EEOF.get("/self-heal/playbook").catch(function () { return {}; }),
      ]);
      SH.incidents = (res[0] || []).map(mapIncident);
      SH.policies = (res[1] || []).map(mapPolicy);
      SH.registry = (res[2] || []).map(function (a) { return a.name; });
      SH.summary = res[3] || null;
      SH.playbook = res[4] || {};
      // Don't repaint over an open modal mid-read; refresh the list underneath.
      SH.renderAll();
      // Deep link (/self-heal/#inc_…) — incidents are live-only now, so re-open
      // once the real incident has arrived from the edge.
      if (!SH.isOpen()) {
        var hash = (location.hash || "").replace(/^#/, "");
        if (hash) SH.openIncident(hash);
      }
    } catch (e) { /* transient edge blip — keep last good render */ }
  }

  // Author a policy against the live edge, then refresh the list + KPI count.
  // Surfaces the edge's `detail` message (e.g. duplicate name) to the form.
  SH.createPolicy = async function (draft) {
    try {
      await EEOF.post("/self-heal/policies", draft);
    } catch (e) {
      // req() throws "<status> <json>"; the edge proxy nests `detail` inside
      // `detail`, so drill through until we reach the human string.
      var msg = (e && e.message) || "create failed";
      var m = /^\d+\s+(.*)$/.exec(msg);
      if (m) {
        try {
          var d = JSON.parse(m[1]);
          while (d && typeof d === "object") d = d.detail;
          msg = (typeof d === "string" && d) || m[1];
        } catch (_) { msg = m[1]; }
      }
      throw new Error(msg);
    }
    await hydrate();
  };

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
