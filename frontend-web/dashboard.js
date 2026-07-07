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

  if (document.readyState !== "loading") refresh();
  else document.addEventListener("DOMContentLoaded", refresh);
  setInterval(refresh, 3000);
})();
