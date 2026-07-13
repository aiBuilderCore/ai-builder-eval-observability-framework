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
  // Normalize `localhost` -> `127.0.0.1`. The edge (uvicorn) binds IPv4 only,
  // but on Windows `localhost` resolves to IPv6 `::1` first, so every fetch +
  // the WebSocket paid a connect-refused-then-retry penalty before falling back
  // to IPv4. Pinning the host removes that per-request delay. macOS was fast
  // either way, which is why this only bit on Windows.
  const ORIGIN =
    location.origin && location.origin.startsWith("http")
      ? location.origin.replace("://localhost", "://127.0.0.1")
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
  // pending: job_id -> { resolve, reject, onProgress?, onFrame?, rejectOnFail }
  //   onProgress(progress, frame) — submitAndWatch's per-tick callback.
  //   onFrame(frame)              — watchJob's every-frame callback.
  //   rejectOnFail                — true → reject the promise on a failed job;
  //                                 false → resolve on any terminal state so a
  //                                 detail page can repaint the failed state.
  let ws = null;
  let wsReady = null;
  const pending = new Map();

  function connect() {
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return wsReady;
    ws = new WebSocket(ORIGIN.replace("http", "ws") + "/api/v1/ws");
    wsReady = new Promise((resolve, reject) => {
      ws.onopen = () => resolve();
      // A socket that errors before opening rejects wsReady, so callers can
      // fall back to REST polling instead of hanging.
      ws.onerror = () => reject(new Error("websocket connect failed"));
    });
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      const p = pending.get(m.job_id);
      if (!p) return;
      if (p.onFrame) p.onFrame(m);
      if (m.progress && p.onProgress) p.onProgress(m.progress, m);
      const terminal =
        m.state === "ready" || m.state === "shipped" || m.state === "failed";
      if (!terminal) return;
      pending.delete(m.job_id);
      if (m.state === "failed" && p.rejectOnFail) {
        p.reject(new Error(m.error?.message || "job failed"));
      } else {
        p.resolve(m);
      }
    };
    ws.onclose = () => {
      ws = null;
      // A mid-flight disconnect settles every watcher so it can recover
      // (fall back to polling) rather than hang on a dead socket.
      for (const [id, p] of pending) {
        pending.delete(id);
        p.reject(new Error("websocket closed"));
      }
    };
    return wsReady;
  }

  // Submit an async job body to `path`, then resolve when it completes,
  // invoking onProgress({done,total,phase}) on each tick.
  async function submitAndWatch(path, body, onProgress) {
    const accepted = await req("POST", path, body);
    const jobId = accepted.job_id;
    await connect();
    const done = new Promise((resolve, reject) =>
      pending.set(jobId, { resolve, reject, onProgress, rejectOnFail: true })
    );
    ws.send(JSON.stringify({ type: "subscribe", job_id: jobId }));
    const final = await done;
    return { accepted, final, result: final.result || {} };
  }

  // Watch an already-submitted job over the shared socket. Fires onFrame(frame)
  // on every status push (including the snapshot the edge replays on subscribe,
  // which covers an already-finished job) and resolves on any terminal state so
  // the caller can do a final repaint. Rejects only if the socket can't be
  // established or drops — letting the caller fall back to REST polling.
  async function watchJob(jobId, onFrame) {
    await connect();
    const done = new Promise((resolve, reject) =>
      pending.set(jobId, { resolve, reject, onFrame, rejectOnFail: false })
    );
    ws.send(JSON.stringify({ type: "subscribe", job_id: jobId }));
    return done;
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
    // Resolved identity (subject/email/name) — the sidebar renders from this so
    // the user block and every submitted_by share one backend source of truth.
    me: () => req("GET", "/me"),
    submitAndWatch,
    watchJob,
    pollJob,
    connect,
  };
})();
