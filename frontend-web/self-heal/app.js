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

  // ── Render helpers ──────────────────────────────────────────────────────────
  function stageChip(stage) {
    return '<span class="chip stage-badge stage-badge--' + stage + '">' + esc(STAGE_LABEL[stage]) + "</span>";
  }
  function dispoChip(inc) {
    return '<span class="chip chip--' + inc.dispoClass + '">' + esc(inc.dispo) + "</span>";
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

  function renderPolicies() {
    document.getElementById("policies").innerHTML = SH.policies.length
      ? SH.policies.map(function (p) {
          return (
            '<p class="dsl__name">' + esc(p.name) + "</p>" +
            '<pre class="dsl">' + p.lines.map(function (l) { return l[0]; }).join("\n") + "</pre>"
          );
        }).join("")
      : '<span class="sh-empty__sub">Loading policies from the edge…</span>';
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
      SH.renderAll();
      // Deep link (/self-heal/#inc_…) — incidents are live-only now, so re-open
      // once the real incident has arrived from the edge.
      if (!SH.isOpen()) {
        var hash = (location.hash || "").replace(/^#/, "");
        if (hash) SH.openIncident(hash);
      }
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
