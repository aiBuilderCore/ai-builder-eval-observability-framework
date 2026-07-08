// ============================================================
// Persona Lab — CRUD backed by the live /personas edge
// Eval & Observability Framework · synthetic data only
// No bundled seed: the list hydrates from the backend and shows an honest
// empty state when the workspace has no personas yet. localStorage is only a
// same-session cache of real, API-backed personas.
// ============================================================

const STORAGE_KEY = "aibcore.persona-lab.personas.v2";
const HUES = ["ochre", "sage", "rose", "olive", "plum", "rust", "terracotta"];
const TONES = ["formal", "casual", "blunt", "frustrated", "playful"];
const TONE_LABEL = {
  formal: "Formal",
  casual: "Casual",
  blunt: "Blunt",
  frustrated: "Frustrated",
  playful: "Playful",
};
const TECH = ["novice", "intermediate", "advanced"];
const TECH_LABEL = {
  novice: "Novice — first time touching this kind of tool",
  intermediate: "Intermediate — comfortable, occasional gaps",
  advanced: "Advanced — power user / expert practitioner",
};

// ---------- Seed library ----------------------------------------------
const SEED = [];

// ---------- Storage (live API mirror; localStorage is the offline cache) ----
// The synchronous facade (load/get/upsert/remove) is preserved so the pages
// need no changes. On load we hydrate the cache from GET /personas and repaint;
// writes go through to the edge and re-hydrate. If the edge is unreachable
// everything falls back to localStorage/seed — the UI never breaks.
let CACHE = null;

function readLS() {
  try { const r = localStorage.getItem(STORAGE_KEY); return r ? JSON.parse(r) : null; }
  catch { return null; }
}
function saveAll(personas) { CACHE = personas; localStorage.setItem(STORAGE_KEY, JSON.stringify(personas)); }

function load() {
  if (CACHE) return CACHE;
  const ls = readLS();
  CACHE = Array.isArray(ls) ? ls : [];
  return CACHE;
}
function get(id) { return load().find(p => p.id === id) || null; }

function normalize(p) {
  return { ...p,
    goals: p.goals || [], edge_cases: p.edge_cases || [], tags: p.tags || [],
    created_at: (p.created_at || "").slice(0, 10),
    updated_at: (p.updated_at || "").slice(0, 10) };
}
function toDraft(p) {
  return {
    name: p.name, quote: p.quote || "", role: p.role || "", age_band: p.age_band || "",
    locale: p.locale || "", tech_savviness: p.tech_savviness || "intermediate",
    tone: p.tone || "casual", goals: p.goals || [], edge_cases: p.edge_cases || [],
    tags: p.tags || [], hue: p.hue || "ochre", version: p.version || "1.0.0",
    primary_rubric: p.primary_rubric || "helpfulness",
    default_shapes: p.default_shapes || [], default_scenarios: p.default_scenarios || [],
  };
}

async function hydrate() {
  if (!window.EEOF) return;
  try {
    // Live is the single source of truth — never inject a seed library into the
    // real backend. An empty backend renders an honest empty state.
    const live = await window.EEOF.get("/personas");
    saveAll((live || []).map(normalize));
    if (typeof window.render === "function") window.render();
  } catch { /* offline — keep the localStorage cache of real personas */ }
}

async function upsert(persona) {
  const all = load();
  const idx = all.findIndex(p => p.id === persona.id);
  if (idx >= 0) all[idx] = persona; else all.unshift(persona);
  saveAll(all);
  if (!window.EEOF) return;
  try {
    if (idx >= 0 && !persona.__new) {
      await window.EEOF.put(`/personas/${persona.id}?level=patch`, toDraft(persona));
    } else {
      await window.EEOF.post("/personas", toDraft(persona));
    }
    await hydrate();
  } catch { toast("Saved locally (edge offline)", "Persona Lab"); }
}

async function remove(id) {
  saveAll(load().filter(p => p.id !== id));
  if (!window.EEOF) return;
  try { await window.EEOF.del(`/personas/${id}`); await hydrate(); } catch {}
}

// Kick a hydrate as soon as the DOM is ready so pages show live data.
if (document.readyState !== "loading") setTimeout(hydrate, 0);
else document.addEventListener("DOMContentLoaded", hydrate);

// ---------- Helpers --------------------------------------------------
function monogramOf(name) {
  if (!name) return "··";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
function slugify(s) {
  return (s || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/(^_|_$)/g, "")
    .slice(0, 40);
}
function newId(name) {
  const base = "persona_" + (slugify(name) || "untitled");
  // disambiguate if collision
  const all = load();
  if (!all.some(p => p.id === base)) return base;
  for (let n = 2; n < 999; n++) {
    const cand = `${base}_${n}`;
    if (!all.some(p => p.id === cand)) return cand;
  }
  return base + "_" + Date.now();
}
function bumpVersion(v, kind = "patch") {
  const m = String(v || "0.0.0").match(/^(\d+)\.(\d+)\.(\d+)/);
  let [_, maj, min, pat] = m || [null, "0", "0", "0"];
  maj = +maj; min = +min; pat = +pat;
  if (kind === "major") { maj++; min = 0; pat = 0; }
  else if (kind === "minor") { min++; pat = 0; }
  else { pat++; }
  return `${maj}.${min}.${pat}`;
}
function todayISO() { return new Date().toISOString().slice(0, 10); }

// ---------- Toast / modal --------------------------------------------
function toast(message, accent) {
  let host = document.querySelector(".toast-host");
  if (!host) {
    host = document.createElement("div");
    host.className = "toast-host";
    document.body.appendChild(host);
  }
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = accent ? `<b>${accent}</b> · ${message}` : message;
  host.appendChild(el);
  setTimeout(() => el.remove(), 2900);
}

function confirmModal({ title, body, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const host = document.createElement("div");
    host.className = "modal-host";
    host.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <h4>${title}</h4>
        <p>${body}</p>
        <div class="actions">
          <button class="btn ghost" data-act="cancel">Cancel</button>
          <button class="btn ${danger ? 'danger' : 'primary'}" data-act="ok">${confirmLabel}</button>
        </div>
      </div>`;
    document.body.appendChild(host);
    host.addEventListener("click", (e) => {
      if (e.target === host) close(false);
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "ok") close(true);
      if (act === "cancel") close(false);
    });
    function close(v) { host.remove(); resolve(v); }
  });
}

// expose
window.PL = {
  HUES, TONES, TONE_LABEL, TECH, TECH_LABEL,
  load, saveAll, get, upsert, remove,
  monogramOf, slugify, newId, bumpVersion, todayISO,
  toast, confirmModal,
};
