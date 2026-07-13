// Live dashboard — repaints the Control Center landing from the API
// Orchestration edge. Every number here is derived from a real endpoint; the
// seed markup in index.html is the offline fallback when the edge is down.
//
// Design notes for the dashboard-enhancement pass:
//  - One canonical "open items" counter (§1.1): observability flags + self-heal
//    incidents + failed jobs, computed once and reused, so no two tiles disagree.
//  - Real system health (§1.2) from /system/health — never fabricated uptime.
//  - Pillar delta is cross-sectional ("vs pillar avg"), rendered with neutral
//    glyphs, not up/down trend arrows (§1.5).
//  - Severity-led hero + gate (A/C), drill-through (D), legible jobs (§1.6).
//  - All six pillars always render, uncovered ones explicit (§1.3).
//  - Judge calibration (E) + agent×pillar coverage (F) + pass-rate sparkline (B).
//  - Polling pauses when the tab is hidden.
(function () {
  if (!window.EEOF) return;

  const GATE_THRESHOLD = 0.8; // matches observability-svc evaluate_gate default
  const PILLARS = ["Safety", "Privacy", "Reliability", "Explainability", "Transparency", "Fairness"];

  const $ = (id) => document.getElementById(id);
  const band = (s) => (s >= 90 ? "ok" : s >= 80 ? "warn" : "err");
  const setText = (id, v) => { const el = $(id); if (el) el.textContent = v; };

  // Custom (BYOJ) judges live client-side in the Evaluation app's localStorage.
  function customJudgeCount() {
    try {
      const arr = JSON.parse(localStorage.getItem("aibcore.eval.customjudges.v1") || "[]");
      return Array.isArray(arr) ? arr.length : 0;
    } catch { return 0; }
  }

  // ── Fast cycle: counts, pipeline cards, jobs, unified attention ───────────
  async function refresh() {
    if (document.hidden) return;
    try {
      const [personas, sets, runs, vsets, jobs, obsIncidents, healIncidents, batches, calibration, judges] =
        await Promise.all([
          EEOF.get("/personas").catch(() => []),
          EEOF.get("/question-sets").catch(() => []),
          EEOF.get("/simulation/runs").catch(() => []),
          EEOF.get("/verdict-sets").catch(() => []),
          EEOF.get("/jobs").catch(() => []),
          EEOF.get("/observability/incidents?state=open").catch(() => []),
          EEOF.get("/self-heal/incidents?status=open").catch(() => []),
          EEOF.get("/observability/batches").catch(() => []),
          EEOF.get("/observability/calibration").catch(() => []),
          EEOF.get("/judges").catch(() => []),
        ]);

      const verdicts = vsets.reduce((n, v) => n + (v.verdict_count || 0), 0);
      const passRates = vsets.filter((v) => v.pass_rate != null).map((v) => v.pass_rate);
      const passRate = passRates.length
        ? Math.round((passRates.reduce((a, b) => a + b, 0) / passRates.length) * 100) + "%"
        : "—";
      const running = (stage) =>
        jobs.filter((j) => j.stage === stage && ["queued", "running"].includes(j.state)).length;
      const failedJobs = jobs.filter((j) => j.state === "failed").length;
      const atRiskGates = vsets.filter((v) => (v.pass_rate ?? 1) < GATE_THRESHOLD).length;

      const obsCount = obsIncidents.length;
      const healOpen = healIncidents.length;
      // One canonical counter — everything that needs a human, counted once.
      const openItems = obsCount + healOpen + failedJobs;

      const totalJudges = judges.length + customJudgeCount();

      // KPI signals owned by this cycle.
      setText("kpiPass", passRate);
      const openEl = $("kpiOpen");
      if (openEl) {
        openEl.textContent = openItems;
        openEl.style.color = openItems ? "var(--warn)" : "var(--ok)";
      }

      // Pipeline stage cards — Persona · QGen · Sim · Judge Catalogue · Eval ·
      // Observability · Self Heal.
      const bigs = document.querySelectorAll(".stage__num-big");
      const chips = [...document.querySelectorAll(".stage .chip")];
      const setCard = (i, big, chipText, chipCls) => {
        if (bigs[i]) bigs[i].innerHTML = big;
        if (chips[i]) { chips[i].textContent = chipText; chips[i].className = "chip chip--" + chipCls; }
      };
      setCard(0, personas.length, personas.length ? "healthy" : "empty", personas.length ? "ok" : "warn");
      setCard(1, sets.length, running("qgen") ? `${running("qgen")} running` : "idle", running("qgen") ? "run" : "ok");
      setCard(2, runs.length, running("sim") ? `${running("sim")} in flight` : "idle", running("sim") ? "run" : "ok");
      setCard(3, totalJudges, customJudgeCount() ? `${judges.length} + ${customJudgeCount()}` : `${judges.length} built-in`, "ok");
      setCard(4, verdicts.toLocaleString(), passRate !== "—" ? `${passRate} pass` : "no data",
        passRates.length && passRate !== "—" && parseInt(passRate) < 85 ? "warn" : "ok");
      // Observability card = monitor flags (distinct from self-heal incidents).
      setCard(5, `${batches.length} <em>batches</em>`, `${obsCount} flag${obsCount === 1 ? "" : "s"}`, obsCount ? "warn" : "ok");
      // Self Heal card = its own incident store (the real breach-driven count).
      setCard(6, healOpen, healOpen ? `${healOpen} open` : "auto", healOpen ? "warn" : "ok");

      renderJobs(jobs);
      renderRail({ vsets, calibration, jobs, obsIncidents, healIncidents });
    } catch {}
  }

  // ── Unified "Needs attention" rail (§1.1) ─────────────────────────────────
  function renderRail({ vsets, calibration, jobs, obsIncidents, healIncidents }) {
    const rail = document.querySelector(".rail"); // first .rail = Needs attention
    if (!rail) return;
    const items = [];
    vsets.filter((v) => (v.pass_rate ?? 1) < GATE_THRESHOLD).forEach((v) =>
      items.push(["err", "observability/gate.html", `Deploy gate at risk — ${v.id.slice(0, 12)}`,
        `eval pass ${Math.round((v.pass_rate ?? 0) * 100)}% < ${GATE_THRESHOLD * 100}% threshold`]));
    calibration.filter((c) => (c.kappa ?? 1) < 0.6).forEach((c) =>
      items.push(["warn", "observability/calibration.html", `Judge κ low on ${c.judge_ref}`,
        `κ ${c.kappa} vs human baseline`]));
    jobs.filter((j) => j.state === "failed").forEach((j) =>
      items.push(["err", "#", `${j.stage} job failed`, (j.error || {}).message || "worker error"]));
    (healIncidents || []).slice(0, 3).forEach((i) =>
      items.push(["warn", "self-heal/index.html", i.summary || i.title || "Self-heal incident",
        i.severity || i.stage || "open"]));
    (obsIncidents || []).slice(0, 2).forEach((i) =>
      items.push(["warn", "observability/monitors.html", i.summary || "Monitor flag", i.severity || "medium"]));
    jobs.filter((j) => ["queued", "running"].includes(j.state)).slice(0, 2).forEach((j) =>
      items.push(["run", "#", `${j.stage} job running`,
        `${(j.progress || {}).done || 0}/${(j.progress || {}).total || 0} · ${(j.progress || {}).phase || j.state}`]));

    const railLink = rail.closest(".card")?.querySelector(".card__link");
    if (railLink) railLink.textContent = `${items.length} open`;
    rail.innerHTML = items.length
      ? items.slice(0, 6).map(([dot, href, title, meta]) => `
        <a class="alert" href="${href}">
          <span class="alert__dot alert__dot--${dot}"></span>
          <span class="alert__body">
            <p class="alert__title">${esc(title)}</p>
            <span class="alert__meta">${esc(meta)}</span>
          </span>
          <span class="alert__go" aria-hidden="true">→</span>
        </a>`).join("")
      : `<p style="color:var(--text-muted);font-size:13px;padding:8px 2px;">Nothing needs attention — all gates green.</p>`;
  }

  const STAGE_LABEL = { qgen: "Question Gen", sim: "Simulation", eval: "Evaluation", obs: "Observability", heal: "Self Heal" };
  const STAGE_TAG = { qgen: "question-generation", sim: "simulation", eval: "evaluation", obs: "observability", heal: "self-heal" };

  // Human-readable result + detail per job kind (§1.6).
  function jobResult(j) {
    const r = j.result || {};
    if (r.pass_rate != null) return `${Math.round(r.pass_rate * 100)}% pass`;
    if (r.verdict_count != null) return `${r.verdict_count} verdicts`;
    if (r.question_count != null) return `${r.question_count} items`;
    if (r.run_id) return "run";
    if (j.state === "failed") return "failed";
    const d = (j.progress || {}).detail || {};
    if (d.verdicts_emitted != null) return `${d.verdicts_emitted} verdicts`;
    return j.state === "ready" || j.state === "shipped" ? "done" : "…";
  }
  function jobDetail(j) {
    const inp = j.inputs || {};
    if (j.stage === "eval") return `${(inp.run_ids || []).length} run · ${(inp.judge_refs || []).length} judges`;
    if (j.stage === "sim") {
      const snap = inp.adapter_snapshot || {};
      return snap.display_name || (snap.config || {}).display_name || snap.name || "agent run";
    }
    if (j.stage === "qgen") return `${inp.strategy || "set"} · ${(inp.persona_snapshots || []).length} persona`;
    if (j.stage === "obs") return "evidence pack";
    return (j.kind || "").split(".").pop();
  }

  function renderJobs(jobs) {
    const body = $("jobsBody");
    if (!body) return;
    const rows = jobs
      .sort((a, b) => (b.submitted_at || "").localeCompare(a.submitted_at || ""))
      .slice(0, 12);
    setText("jobsCount", `${rows.length} latest`);
    body.innerHTML = rows.map((j) => {
      const short = (j.job_id || "").replace(/^job_/, "").slice(0, 6);
      const cls = j.state === "ready" || j.state === "shipped" ? "ok" : j.state === "failed" ? "err" : "run";
      return `<tr data-stage="${STAGE_TAG[j.stage] || j.stage}">
        <td class="mono">${esc(short)}</td>
        <td><span class="jtag">${esc(STAGE_LABEL[j.stage] || j.stage)}</span></td>
        <td class="hide-sm jdetail">${esc(jobDetail(j))}</td>
        <td class="hide-md jtime">${esc((j.submitted_at || "").slice(11, 19))}</td>
        <td class="num">${esc(jobResult(j))}</td>
        <td><span class="chip chip--${cls}">${esc(j.state)}</span></td>
      </tr>`;
    }).join("");
  }

  // ── Quality cycle: hero, apps, six pillars, sparkline, calibration,
  //    coverage, spend, system health ────────────────────────────────────────
  function deltaMark(d) {
    // Cross-sectional spread vs the pillar mean — a neutral bar, not a trend arrow.
    if (d > 0) return `<em style="color:var(--ok);font-style:normal" title="above pillar average">+${d}</em>`;
    if (d < 0) return `<em style="color:var(--err);font-style:normal" title="below pillar average">−${-d}</em>`;
    return `<em style="color:var(--text-faint);font-style:normal">±0</em>`;
  }

  function renderQuality(q) {
    const apps = (q && q.applications) || [];
    const pillars = (q && q.pillars) || [];
    const appsHost = $("qualityApps");
    if (appsHost) {
      if (!apps.length) {
        appsHost.innerHTML = `<p style="color:var(--text-muted);font-size:13px;padding:10px 2px;">No applications onboarded yet — quality scores appear here once an agent is registered.</p>`;
      } else {
        const rows = apps.map((a) => {
          const b = band(a.score);
          // Drill-through (§1.4/D): each row links to the evaluation catalogue.
          return `<a class="spend__row" href="evaluation/index.html" style="text-decoration:none;color:inherit" title="${esc(a.evaluations || 0)} evaluations — open Evaluation">
            <span class="spend__name">${esc(a.name)}</span>
            <span class="spend__track"><span class="spend__fill" style="width:${a.score}%;background:var(--${b})"></span></span>
            <span class="spend__val"><b style="color:var(--${b})">${a.score}</b></span></a>`;
        }).join("");
        const scroll = apps.length > 6 ? ` style="max-height:232px;overflow-y:auto"` : "";
        appsHost.innerHTML = `<div class="qa-list"${scroll}>${rows}</div>` +
          `<div class="spend__total"><span>platform mean · ${apps.length} app${apps.length === 1 ? "" : "s"}</span><b>${q.platform_mean}</b></div>`;
      }
    }

    // Six pillars, always — uncovered ones explicit (§1.3).
    const pillHost = $("qualityPillars");
    const present = new Map(pillars.map((p) => [p.name, p]));
    if (pillHost) {
      const covered = pillars.filter((p) => p.score != null);
      const weakest = covered.length ? covered.reduce((m, p) => (p.score < m.score ? p : m)) : null;
      pillHost.innerHTML = PILLARS.map((name) => {
        const p = present.get(name);
        if (!p) {
          return `<div class="spend__row spend__row--nodata" title="no judge has scored this pillar yet">
            <span class="spend__name">${name}</span>
            <span class="spend__track"><span class="spend__fill" style="width:100%"></span></span>
            <span class="spend__val">not tested</span></div>`;
        }
        return `<div class="spend__row"><span class="spend__name">${name}</span>
          <span class="spend__track"><span class="spend__fill" style="width:${p.score}%"></span></span>
          <span class="spend__val">${p.score} ${deltaMark(p.delta)}</span></div>`;
      }).join("") +
        `<div class="spend__total"><span>weakest tested pillar</span><b style="color:var(--warn)">${weakest ? weakest.name : "—"}</b></div>`;
      setText("kpiWeakest", weakest ? weakest.name : "—");
    }

    // KPI quality + hero severity.
    const qEl = $("kpiQuality");
    if (qEl && apps.length) {
      qEl.textContent = q.platform_mean;
      qEl.style.color = `var(--${band(q.platform_mean)})`;
    }
    return { apps, pillars, present };
  }

  // Sparkline (B): pass-rate across successive verdict sets.
  function renderTrend(trend) {
    const host = $("qualityTrend");
    if (!host) return;
    const pts = (trend && trend.points) || [];
    if (pts.length < 2) {
      host.innerHTML = pts.length
        ? `<span class="spark__cap">${pts[0].pass_rate}% · 1 eval</span>`
        : `<span class="spark__cap">no trend yet</span>`;
      return;
    }
    const w = 96, h = 22, vals = pts.map((p) => p.pass_rate);
    const max = 100, min = 0;
    const x = (i) => (i / (pts.length - 1)) * w;
    const y = (v) => h - ((v - min) / (max - min)) * h;
    const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const last = vals[vals.length - 1], prev = vals[vals.length - 2];
    const delta = last - prev;
    const trendCol = delta > 0 ? "var(--ok)" : delta < 0 ? "var(--err)" : "var(--text-faint)";
    host.innerHTML =
      `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="none" aria-hidden="true">
        <path d="${d}" stroke="var(--accent)" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${x(pts.length - 1).toFixed(1)}" cy="${y(last).toFixed(1)}" r="2.2" fill="${trendCol}"/>
      </svg>` +
      `<span class="spark__cap">${last}% <span style="color:${trendCol}">${delta > 0 ? "▲" : delta < 0 ? "▼" : "→"}${Math.abs(delta)}</span> · ${pts.length} evals</span>`;
  }

  // Gate + worst-agent hero (A/C).
  function renderHero(quality, gate) {
    const el = $("heroBanner");
    if (!el) return;
    const apps = (quality && quality.apps) || [];
    if (!apps.length) { el.hidden = true; return; }
    el.hidden = false;
    const worst = apps.reduce((m, a) => (a.score < m.score ? a : m));
    const covered = (quality.pillars || []).filter((p) => p.score != null);
    const weakest = covered.length ? covered.reduce((m, p) => (p.score < m.score ? p : m)) : null;

    const decision = gate && gate.decision; // pass | fail | no_data
    let sev, badge, gateLine;
    if (decision === "fail") { sev = "err"; badge = "Deploy blocked"; }
    else if (decision === "pass") { sev = worst.score < 90 ? "warn" : "ok"; badge = "Gate pass"; }
    else { sev = worst.score < 80 ? "err" : worst.score < 90 ? "warn" : "ok"; badge = "No gate yet"; }
    if (gate && gate.pass_rate != null) {
      gateLine = `Deploy gate ${decision === "pass" ? "PASS" : decision === "fail" ? "BLOCKED" : "—"} · pass ${Math.round(gate.pass_rate * 100)}% vs ${Math.round((gate.threshold ?? GATE_THRESHOLD) * 100)}% threshold`;
    } else {
      gateLine = "No candidate evaluated against the deploy gate yet.";
    }

    el.className = `hero hero--${sev}`;
    setText("heroBadge", badge);
    setText("heroTitle", `${worst.name} — ${worst.score}/100 overall`);
    setText("heroMeta", `${gateLine}${weakest ? ` · weakest pillar ${weakest.name} ${weakest.score}` : ""}`);
    // KPI gate tile.
    const gEl = $("kpiGate");
    if (gEl) {
      gEl.textContent = decision === "pass" ? "PASS" : decision === "fail" ? "BLOCKED" : "—";
      gEl.style.color = decision === "pass" ? "var(--ok)" : decision === "fail" ? "var(--err)" : "var(--text-faint)";
    }
  }

  // Judge calibration (E).
  function renderCalibration(rows) {
    const host = $("calibBody");
    if (!host) return;
    if (!rows || !rows.length) {
      host.innerHTML = `<p style="color:var(--text-muted);font-size:13px;padding:10px 2px;">No calibration yet — appears once judges have scored against a human baseline.</p>`;
      return;
    }
    const kcls = (k) => (k >= 0.8 ? "ok" : k >= 0.6 ? "warn" : "err");
    const mean = rows.reduce((a, r) => a + (r.kappa ?? 0), 0) / rows.length;
    setText("calibMeta", `mean κ ${mean.toFixed(2)} · ${rows.length} judges`);
    host.innerHTML = rows.map((r) => {
      const k = r.kappa ?? 0, b = kcls(k), pct = Math.round(Math.max(0, Math.min(1, k)) * 100);
      return `<div class="spend__row">
        <span class="spend__name">${esc((r.judge_ref || "").replace(/@v\d+$/, ""))}</span>
        <span class="spend__track"><span class="spend__fill" style="width:${pct}%;background:var(--${b})"></span></span>
        <span class="spend__val"><span class="kpill kpill--${b}">κ ${k.toFixed(2)}</span></span></div>`;
    }).join("") +
      `<div class="spend__total"><span>agreement with human baseline</span><b style="color:var(--${kcls(mean)})">κ ${mean.toFixed(2)}</b></div>`;
  }

  // Agent × pillar coverage heatmap (F).
  function renderCoverage(cov) {
    const host = $("coverageBody");
    if (!host) return;
    const pillars = (cov && cov.pillars) || [];
    const agents = (cov && cov.agents) || [];
    if (!agents.length) {
      host.innerHTML = `<p style="color:var(--text-muted);font-size:13px;padding:10px 2px;">No coverage yet — the matrix fills in as agents are evaluated.</p>`;
      return;
    }
    const abbr = { Safety: "Saf", Privacy: "Priv", Reliability: "Rel", Explainability: "Expl", Transparency: "Trans", Fairness: "Fair" };
    let tested = 0, total = 0;
    const head = `<tr><th class="heat__agenth">Agent</th>${pillars.map((p) => `<th title="${p}">${abbr[p] || p.slice(0, 4)}</th>`).join("")}</tr>`;
    const rows = agents.map((row) => {
      const cells = row.pillars.map((c) => {
        total++;
        if (c.score == null) return `<td class="heat__cell heat__cell--none" title="${c.pillar}: not tested">—</td>`;
        tested++;
        const b = band(c.score);
        return `<td class="heat__cell" style="background:var(--${b}-bg);color:var(--${b})" title="${c.pillar}: ${c.score} · ${c.count} verdicts">${c.score}</td>`;
      }).join("");
      return `<tr><td class="heat__agent" title="${esc(row.agent)}">${esc(row.agent)}</td>${cells}</tr>`;
    }).join("");
    host.innerHTML = `<table class="heat">${head}${rows}</table>`;
    setText("coverageMeta", `${tested}/${total} cells tested`);
  }

  // Spend by stage.
  function renderSpend(spend) {
    const host = $("spendBody");
    if (!host || !spend || !spend.stages) return;
    const max = Math.max(...spend.stages.map((s) => s.amount), 0.01);
    host.innerHTML = spend.stages.map((s) =>
      `<div class="spend__row"><span class="spend__name">${esc(s.label)}</span><span class="spend__track"><span class="spend__fill" style="width:${Math.round((s.amount / max) * 100)}%"></span></span><span class="spend__val">$${s.amount.toFixed(2)}</span></div>`
    ).join("") +
      `<div class="spend__total"><span>total · llm + judges</span><b>$${spend.total.toFixed(2)}</b></div>`;
    setText("kpiSpend", `$${spend.total.toFixed(2)}`);
  }

  // Real system health (§1.2) — replaces the fabricated ScyllaDB/Azure rows.
  function renderSystemHealth(h) {
    const host = $("systemHealth");
    if (!host || !h) return;
    const items = [];
    const svcOk = h.services_up === h.services_total;
    items.push([svcOk ? "ok" : "err", "observability/index.html",
      `${h.services_up}/${h.services_total} capability services healthy`,
      h.edge && h.edge.up ? "edge API up · single origin" : "edge degraded"]);
    const dp = h.data_plane || {};
    items.push(["ok", "settings.html", `Data plane: ${dp.kind || dp.mode}`, `${dp.mode} mode`]);
    const prov = h.provider || {};
    if (prov.degraded) {
      const missing = (prov.chain || []).filter((c) => !c.available).map((c) => c.provider).join(", ");
      items.push(["warn", "settings.html", `Model provider degraded — serving from ${prov.active}`,
        `${prov.configured} unavailable${missing ? ` (${missing})` : ""}`]);
    } else {
      items.push(["ok", "settings.html", `Model provider: ${prov.active || "—"}`, "primary healthy"]);
    }
    host.innerHTML = items.map(([dot, href, title, meta]) => `
      <a class="alert" href="${href}">
        <span class="alert__dot alert__dot--${dot}"></span>
        <span class="alert__body">
          <p class="alert__title">${esc(title)}</p>
          <span class="alert__meta">${esc(meta)}</span>
        </span>
        <span class="alert__go" aria-hidden="true">→</span>
      </a>`).join("");
    setText("kpiProvider", prov.active || "—");
    const provEl = $("kpiProvider");
    if (provEl) provEl.style.color = prov.degraded ? "var(--warn)" : "var(--ok)";
  }

  function renderHealSummary(summary) {
    if (!summary) return;
    setText("kpiHealed", summary.auto_resolved_24h ?? 0);
    const meta = $("healthMeta");
    if (meta) meta.textContent = `${summary.auto_resolved_24h ?? 0} auto-healed · MTTR ${summary.median_mttr || "—"}`;
  }

  async function refreshQuality() {
    if (document.hidden) return;
    try {
      const [q, summary, spend, calibration, coverage, trend, sysHealth, vsets] = await Promise.all([
        EEOF.get("/observability/quality").catch(() => null),
        EEOF.get("/self-heal/summary").catch(() => null),
        EEOF.get("/observability/spend").catch(() => null),
        EEOF.get("/observability/calibration").catch(() => []),
        EEOF.get("/observability/coverage").catch(() => null),
        EEOF.get("/observability/quality/trend").catch(() => null),
        EEOF.get("/system/health").catch(() => null),
        EEOF.get("/verdict-sets").catch(() => []),
      ]);

      const quality = renderQuality(q);
      renderHealSummary(summary);
      renderSpend(spend);
      renderCalibration(calibration);
      renderCoverage(coverage);
      renderTrend(trend);
      renderSystemHealth(sysHealth);

      // Gate the latest verdict set (the candidate) for the hero.
      let gate = null;
      if (vsets.length) {
        const latest = vsets.slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""))[0];
        gate = await EEOF.get(`/observability/gate/${latest.id}`).catch(() => null);
      }
      renderHero(quality, gate);
    } catch {}
  }

  // Scope + identity (§1.7) — from the resolved principal, not hardcoded.
  async function refreshMe() {
    try {
      const me = await EEOF.me();
      if (!me) return;
      document.querySelectorAll("[data-eyebrow-tenant]").forEach((e) => (e.textContent = me.tenant || "—"));
      document.querySelectorAll("[data-ws-name]").forEach((e) => (e.textContent = me.workspace || "—"));
      document.querySelectorAll("[data-ws-scope]").forEach((e) => (e.textContent = me.role || (me.admin ? "admin" : "member")));
    } catch {}
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function boot() { refreshMe(); refresh(); refreshQuality(); }
  if (document.readyState !== "loading") boot();
  else document.addEventListener("DOMContentLoaded", boot);

  setInterval(refresh, 3000);
  setInterval(refreshQuality, 5000);
  // Repaint immediately when the tab regains focus (polling pauses while hidden).
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { refresh(); refreshQuality(); } });
})();
