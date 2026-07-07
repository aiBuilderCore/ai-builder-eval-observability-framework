// Live dashboard — replaces the hardcoded KPI numbers + jobs table on the
// framework landing with counts computed from the API Orchestration edge.
(function () {
  if (!window.EEOF) return;

  function setKpi(index, value) {
    const nums = document.querySelectorAll(".aibc-stat__num");
    if (nums[index]) nums[index].textContent = value;
  }

  const GATE_THRESHOLD = 0.85;

  async function refresh() {
    try {
      const [personas, sets, runs, vsets, jobs, incidents, batches, calibration] =
        await Promise.all([
          EEOF.get("/personas").catch(() => []),
          EEOF.get("/question-sets").catch(() => []),
          EEOF.get("/simulation/runs").catch(() => []),
          EEOF.get("/verdict-sets").catch(() => []),
          EEOF.get("/jobs").catch(() => []),
          EEOF.get("/observability/incidents?state=open").catch(() => []),
          EEOF.get("/observability/batches").catch(() => []),
          EEOF.get("/observability/calibration").catch(() => []),
        ]);
      const verdicts = vsets.reduce((n, v) => n + (v.verdict_count || 0), 0);
      const passRates = vsets.filter((v) => v.pass_rate != null).map((v) => v.pass_rate);
      const passRate = passRates.length
        ? Math.round((passRates.reduce((a, b) => a + b, 0) / passRates.length) * 100) + "%"
        : "—";
      const running = (stage) =>
        jobs.filter((j) => j.stage === stage && ["queued", "running"].includes(j.state)).length;
      const openFlags = incidents.length;

      // KPI strip — six .aibc-stat tiles.
      setKpi(0, passRate);
      setKpi(1, personas.length);
      setKpi(2, sets.length);
      setKpi(3, runs.length);
      setKpi(4, verdicts.toLocaleString());
      setKpi(5, openFlags);

      // Pipeline stage cards — big metric + status chip.
      const bigs = document.querySelectorAll(".stage__num-big");
      const chips = [...document.querySelectorAll(".stage .chip")];
      const setCard = (i, big, chipText, chipCls) => {
        if (bigs[i]) bigs[i].innerHTML = big;
        if (chips[i]) { chips[i].textContent = chipText; chips[i].className = "chip chip--" + chipCls; }
      };
      setCard(0, personas.length, personas.length ? "healthy" : "empty", personas.length ? "ok" : "warn");
      setCard(1, sets.length, running("qgen") ? `${running("qgen")} running` : "idle", running("qgen") ? "run" : "ok");
      setCard(2, runs.length, running("sim") ? `${running("sim")} in flight` : "idle", running("sim") ? "run" : "ok");
      setCard(3, verdicts.toLocaleString(), `${passRate} pass`, passRates.length && passRate !== "—" && parseInt(passRate) < 85 ? "warn" : "ok");
      setCard(4, `${batches.length} <em>batches</em>`, `${openFlags} flags`, openFlags ? "warn" : "ok");

      renderJobs(jobs);
      renderRail(jobs, vsets, calibration, incidents);
    } catch {}
  }

  function renderRail(jobs, vsets, calibration, incidents) {
    const rail = document.querySelector(".rail");
    if (!rail) return;
    const items = [];
    vsets.filter((v) => (v.pass_rate ?? 1) < GATE_THRESHOLD).forEach((v) =>
      items.push(["err", "observability/gate.html", `Deploy gate at risk — ${v.id.slice(0, 10)}`,
        `eval pass ${Math.round(v.pass_rate * 100)}% < ${GATE_THRESHOLD * 100}% threshold`]));
    calibration.filter((c) => (c.kappa ?? 1) < 0.6).forEach((c) =>
      items.push(["warn", "observability/calibration.html", `Judge κ low on ${c.judge_ref}`,
        `κ ${c.kappa} vs baseline`]));
    jobs.filter((j) => j.state === "failed").forEach((j) =>
      items.push(["err", "#", `${j.stage} job failed`, (j.error || {}).message || "worker error"]));
    jobs.filter((j) => ["queued", "running"].includes(j.state)).slice(0, 3).forEach((j) =>
      items.push(["run", "#", `${j.stage} job running`,
        `${(j.progress || {}).done || 0}/${(j.progress || {}).total || 0} · ${(j.progress || {}).phase || j.state}`]));
    incidents.slice(0, 2).forEach((i) =>
      items.push(["warn", "observability/monitors.html", i.summary || "Open incident", i.severity || "medium"]));

    const railLink = rail.closest(".card")?.querySelector(".card__link");
    if (railLink) railLink.textContent = `${items.length} open`;
    rail.innerHTML = items.length
      ? items.slice(0, 6).map(([dot, href, title, meta]) => `
        <a class="alert" href="${href}">
          <span class="alert__dot alert__dot--${dot}"></span>
          <span class="alert__body">
            <p class="alert__title">${title}</p>
            <span class="alert__meta">${meta}</span>
          </span>
          <span class="alert__go" aria-hidden="true">→</span>
        </a>`).join("")
      : `<p style="color:var(--text-muted);font-size:13px;padding:8px 2px;">Nothing needs attention — all gates green.</p>`;
  }

  const STAGE_LABEL = { qgen: "Question Gen", sim: "Simulation", eval: "Evaluation",
    obs: "Observability" };
  const STAGE_TAG = { qgen: "question-generation", sim: "simulation", eval: "evaluation",
    obs: "observability" };

  function renderJobs(jobs) {
    const body = document.getElementById("jobsBody");
    if (!body) return;
    const rows = jobs
      .sort((a, b) => (b.submitted_at || "").localeCompare(a.submitted_at || ""))
      .slice(0, 12);
    const count = document.getElementById("jobsCount");
    if (count) count.textContent = `${rows.length} latest`;
    body.innerHTML = rows.map((j) => {
      const short = j.job_id.replace(/^job_/, "").slice(0, 6);
      const result = j.result
        ? Object.values(j.result)[0]
        : j.state === "failed" ? "—" : "…";
      const cls = j.state === "ready" || j.state === "shipped" ? "ok"
        : j.state === "failed" ? "err" : "run";
      return `<tr data-stage="${STAGE_TAG[j.stage] || j.stage}">
        <td class="mono">${short}</td>
        <td><span class="jtag">${STAGE_LABEL[j.stage] || j.stage}</span></td>
        <td class="hide-sm jdetail">${(j.kind || "").split(".").pop()}</td>
        <td class="hide-md jtime">${(j.submitted_at || "").slice(11, 19)}</td>
        <td class="num">${typeof result === "number" ? result : String(result).slice(0, 10)}</td>
        <td><span class="chip chip--${cls}">${j.state}</span></td>
      </tr>`;
    }).join("");
  }

  // ── Quality at a glance + System health (live from /self-heal/*) ──────────
  // Scales to any app count: the app list renders N rows and scrolls past 6 so
  // the card height is identical for 1 or 10 apps; the pillar card stays a fixed
  // six and the platform mean recomputes from whatever apps exist.
  function band(score) {
    return score >= 90 ? "ok" : score >= 80 ? "warn" : "err";
  }
  function deltaMark(d) {
    if (d > 0) return `<em style="color:var(--ok);font-style:normal">▲${d}</em>`;
    if (d < 0) return `<em style="color:var(--err);font-style:normal">▼${-d}</em>`;
    return `<em style="color:var(--text-faint);font-style:normal">—</em>`;
  }

  function renderQuality(q) {
    const apps = q.applications || [];
    const pillars = q.pillars || [];
    const appsHost = document.getElementById("qualityApps");
    if (appsHost) {
      if (!apps.length) {
        appsHost.innerHTML = `<p style="color:var(--text-muted);font-size:13px;padding:10px 2px;">No applications onboarded yet — quality scores appear here once an agent is registered.</p>`;
      } else {
        const rows = apps.map((a) => {
          const b = band(a.score);
          return `<div class="spend__row"><span class="spend__name">${a.name}</span><span class="spend__track"><span class="spend__fill" style="width:${a.score}%;background:var(--${b})"></span></span><span class="spend__val"><b style="color:var(--${b})">${a.score}</b></span></div>`;
        }).join("");
        // Fixed viewport so 1 app and 10 apps present the same card height.
        const scroll = apps.length > 6
          ? ` style="max-height:232px;overflow-y:auto"` : "";
        appsHost.innerHTML =
          `<div class="qa-list"${scroll}>${rows}</div>` +
          `<div class="spend__total"><span>platform mean · overall quality · ${apps.length} app${apps.length === 1 ? "" : "s"}</span><b>${q.platform_mean}</b></div>`;
      }
    }
    const pillHost = document.getElementById("qualityPillars");
    if (pillHost && pillars.length) {
      const weakest = pillars.reduce((m, p) => (p.score < m.score ? p : m), pillars[0]);
      pillHost.innerHTML =
        pillars.map((p) =>
          `<div class="spend__row"><span class="spend__name">${p.name}</span><span class="spend__track"><span class="spend__fill" style="width:${p.score}%"></span></span><span class="spend__val">${p.score} ${deltaMark(p.delta)}</span></div>`
        ).join("") +
        `<div class="spend__total"><span>weakest pillar · needs attention</span><b style="color:var(--warn)">${weakest.name}</b></div>`;
    }
  }

  function renderHealth(summary) {
    const link = document.querySelector('#systemHealth a[href="self-heal/index.html"] .alert__title');
    if (link && summary) {
      const n = summary.open_incidents;
      link.textContent = `${n} active incident${n === 1 ? "" : "s"} in self-heal`;
    }
    const meta = document.getElementById("healthMeta");
    if (meta && summary) meta.textContent = `${summary.auto_resolved_24h} auto-healed · 24h`;
  }

  // Spend by stage — live from /observability/spend (token + count driven).
  function renderSpend(spend) {
    const host = document.getElementById("spendBody");
    if (!host || !spend || !spend.stages) return;
    const max = Math.max(...spend.stages.map((s) => s.amount), 0.01);
    host.innerHTML = spend.stages.map((s) =>
      `<div class="spend__row"><span class="spend__name">${s.label}</span><span class="spend__track"><span class="spend__fill" style="width:${Math.round((s.amount / max) * 100)}%"></span></span><span class="spend__val">$${s.amount.toFixed(2)}</span></div>`
    ).join("") +
      `<div class="spend__total"><span>total · llm + judges</span><b>$${spend.total.toFixed(2)}</b></div>`;
  }

  async function refreshQuality() {
    try {
      const [q, summary, spend] = await Promise.all([
        EEOF.get("/observability/quality").catch(() => null),
        EEOF.get("/self-heal/summary").catch(() => null),
        EEOF.get("/observability/spend").catch(() => null),
      ]);
      if (q) renderQuality(q);
      if (summary) renderHealth(summary);
      if (spend) renderSpend(spend);
    } catch {}
  }

  if (document.readyState !== "loading") { refresh(); refreshQuality(); }
  else document.addEventListener("DOMContentLoaded", () => { refresh(); refreshQuality(); });
  setInterval(refresh, 3000);
  setInterval(refreshQuality, 5000);
})();
