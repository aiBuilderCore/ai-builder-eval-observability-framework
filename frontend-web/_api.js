// ============================================================================
// _api.js — shared client for the live API Orchestration edge.
//
// Every sub-app loads this before its own app.js. It exposes window.EEOF: a
// thin REST wrapper (auth + error handling), an async-job helper that streams
// status over ONE shared WebSocket, and small mappers. When the edge is
// unreachable the sub-apps fall back to their bundled seed data, so the UI
// always renders (synthetic-only, demo-safe).
// ============================================================================
(function () {
  const ORIGIN =
    location.origin && location.origin.startsWith("http")
      ? location.origin
      : "http://127.0.0.1:8080";
  const BASE = ORIGIN + "/api/v1";
  const HEADERS = { "Content-Type": "application/json", Authorization: "Bearer dev" };

  async function req(method, path, body) {
    const res = await fetch(BASE + path, {
      method,
      headers: HEADERS,
      body: body != null ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = JSON.stringify(await res.json());
      } catch {}
      throw new Error(`${res.status} ${detail}`);
    }
    return res.status === 204 ? null : res.json();
  }

  // Is the edge reachable? Cached probe used to decide live-vs-seed.
  let liveProbe = null;
  async function isLive() {
    if (liveProbe === null) {
      liveProbe = fetch(ORIGIN + "/health")
        .then((r) => r.ok)
        .catch(() => false);
    }
    return liveProbe;
  }

  // ---- One shared WebSocket, multiplexed by job_id -----------------------
  let ws = null;
  let wsReady = null;
  const pending = new Map(); // job_id -> {resolve, reject, onProgress}

  function connect() {
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return wsReady;
    ws = new WebSocket(ORIGIN.replace("http", "ws") + "/api/v1/ws");
    wsReady = new Promise((r) => (ws.onopen = () => r()));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      const p = pending.get(m.job_id);
      if (!p) return;
      if (m.progress && p.onProgress) p.onProgress(m.progress, m);
      if (m.state === "ready" || m.state === "shipped") {
        pending.delete(m.job_id);
        p.resolve(m);
      } else if (m.state === "failed") {
        pending.delete(m.job_id);
        p.reject(new Error(m.error?.message || "job failed"));
      }
    };
    ws.onclose = () => {
      ws = null;
    };
    return wsReady;
  }

  // Submit an async job body to `path`, then resolve when it completes,
  // invoking onProgress({done,total,phase}) on each tick.
  async function submitAndWatch(path, body, onProgress) {
    const accepted = await req("POST", path, body);
    const jobId = accepted.job_id;
    await connect();
    await wsReady;
    const done = new Promise((resolve, reject) =>
      pending.set(jobId, { resolve, reject, onProgress })
    );
    ws.send(JSON.stringify({ type: "subscribe", job_id: jobId }));
    const final = await done;
    return { accepted, final, result: final.result || {} };
  }

  async function pollJob(jobId, { interval = 400, timeout = 90000 } = {}) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const job = await req("GET", `/jobs/${jobId}`);
      if (["ready", "shipped", "failed"].includes(job.state)) return job;
      await new Promise((r) => setTimeout(r, interval));
    }
    throw new Error("job timed out");
  }

  window.EEOF = {
    BASE,
    ORIGIN,
    isLive,
    get: (p) => req("GET", p),
    post: (p, b) => req("POST", p, b),
    put: (p, b) => req("PUT", p, b),
    del: (p) => req("DELETE", p),
    submitAndWatch,
    pollJob,
    connect,
  };
})();
