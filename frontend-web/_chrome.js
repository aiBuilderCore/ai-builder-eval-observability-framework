/* AIBuilderCore app chrome for the Enterprise Eval Observability mock UIs.

   The framework opens as a *fullscreen application* (launched from the
   Applications catalog), not as a docs page. It carries its own shell:

     ┌ Top bar:  AIBuilderCore / Applications ······· scope chips · theme
     ├ Left rail (in-app): app title (→ Dashboard) + the five stages,
     │            and pinned to the bottom the logged-in user + Settings.
     └ Main:     full remaining width (each stage centers its own column).

   Theme toggle shares the `aibc-theme` localStorage key with every other page. */
(function () {
  var thisScript = document.currentScript;
  if (!thisScript || !thisScript.src) return;

  var scriptUrl  = new URL(thisScript.src, location.href);
  var sectionUrl = new URL('./',  scriptUrl);   // .../enterprise-eval-observability-framework/
  var appsUrl    = new URL('../', sectionUrl);  // .../applications/
  var repoUrl    = new URL('../', appsUrl);     // .../ (repo root)

  var herePath = location.pathname;
  var sectionPath = sectionUrl.pathname;
  var activeSub = '';
  if (herePath.indexOf(sectionPath) === 0) {
    var rest = herePath.slice(sectionPath.length);
    var first = rest.split('/')[0] || '';
    // The section landing resolves to `index.html` — that's the Dashboard
    // (product home): no active sub-app, no per-stage scope chips.
    activeSub = first === 'index.html' ? '' : first;
  }
  var isSettings = activeSub === 'settings.html';
  // Judge Catalogue is a sub-page under evaluation/ but gets its own sidebar
  // entry, so highlight it (and not Evaluation) when it's the current page.
  var isCatalog = /\/evaluation\/catalog\.html$/.test(herePath);

  var APP_NAME = 'Enterprise Eval Observability';

  // Logged-in operator — synthetic demo identity, not a persona and not real
  // customer data. Shown in the sidebar user block. Alex is the workspace admin:
  // the only role allowed to register teams and onboard members (see settings).
  var USER = { name: 'Alex Rivera', role: 'Workspace Admin', tenant: 'acme-corp', initials: 'AR', admin: true };

  // Compact inline icons (16×16 stroke). One per stage + settings.
  var ICON = {
    'dashboard':           '<svg viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="9" y="2" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="2" y="9" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="9" y="9" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.3"/></svg>',
    'persona-lab':         '<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="5.4" r="2.5" stroke="currentColor" stroke-width="1.3"/><path d="M3.2 13c0-2.3 2.2-3.6 4.8-3.6S12.8 10.7 12.8 13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>',
    'question-generation': '<svg viewBox="0 0 16 16" fill="none"><path d="M3 3.4h10a1 1 0 0 1 1 1v5.6a1 1 0 0 1-1 1H7l-3 2.2V11H3a1 1 0 0 1-1-1V4.4a1 1 0 0 1 1-1Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>',
    'simulation':          '<svg viewBox="0 0 16 16" fill="none"><path d="M2 8h2.4l1.5-4.2 2.5 8.4 1.5-4.2H14" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    'evaluation':          '<svg viewBox="0 0 16 16" fill="none"><path d="M8 1.8 13 4v3.4c0 3.2-2.1 5.6-5 6.8-2.9-1.2-5-3.6-5-6.8V4l5-2.2Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M5.8 8 7.3 9.5 10.4 6.2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    'observability':       '<svg viewBox="0 0 16 16" fill="none"><path d="M2 8s2.2-4 6-4 6 4 6 4-2.2 4-6 4-6-4-6-4Z" stroke="currentColor" stroke-width="1.2"/><circle cx="8" cy="8" r="1.8" stroke="currentColor" stroke-width="1.2"/></svg>',
    'self-heal':           '<svg viewBox="0 0 16 16" fill="none"><path d="M6.3 3.1a3 3 0 0 0 3.9 3.9l3.1 3.1a1.6 1.6 0 0 1-2.3 2.3L7.9 9.3a3 3 0 0 1-3.9-3.9l1.7 1.7 1.6-.3.3-1.6L6.3 3.1Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M2.6 11.4a5.5 5.5 0 0 0 1.4 1.9" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>',
    'judges':              '<svg viewBox="0 0 16 16" fill="none"><path d="M8 2.2v10.6M4.4 13.4h7.2M8 3.6 3.4 5m4.6-1.4L12.6 5M3.4 5 1.9 8.2h3L3.4 5Zm9.2 0-1.5 3.2h3L12.6 5Z" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    'settings':            '<svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.2"/><path d="M8 1.6v1.6M8 12.8v1.6M14.4 8h-1.6M3.2 8H1.6M12.5 3.5l-1.1 1.1M4.6 11.4l-1.1 1.1M12.5 12.5l-1.1-1.1M4.6 4.6 3.5 3.5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>',
    'sandbox':             '<svg viewBox="0 0 16 16" fill="none"><path d="M8 1.9 13.6 5v6L8 14.1 2.4 11V5L8 1.9Z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/><path d="M2.4 5 8 8.1 13.6 5M8 8.1V14.1" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>',
    'team':                '<svg viewBox="0 0 16 16" fill="none"><circle cx="6" cy="6" r="2.2" stroke="currentColor" stroke-width="1.2"/><path d="M2.2 12.8c0-2.1 1.7-3.3 3.8-3.3s3.8 1.2 3.8 3.3" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/><path d="M10.4 4.3a2.2 2.2 0 0 1 0 4.1M11 9.7c1.6.3 2.6 1.4 2.6 3.1" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>',
    'check':               '<svg viewBox="0 0 16 16" fill="none"><path d="M3.5 8.4 6.4 11.3 12.5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
  };

  // Workspaces govern artifact visibility across *every* stage. Sandbox is the
  // creator's private scope (default); a team workspace makes artifacts visible
  // to everyone on that team. The list is the teams the logged-in user belongs
  // to — all synthetic demo data. Selection persists via `aibc-workspace`.
  var WORKSPACES = [
    { id: 'sandbox',          kind: 'sandbox', name: 'Sandbox',          desc: 'Only you · private', scope: 'visible to you only' },
    { id: 'trust-safety',     kind: 'team',    name: 'Trust & Safety',   desc: '8 members',          scope: 'visible across Trust & Safety' },
    { id: 'finance-copilot',  kind: 'team',    name: 'Finance Copilot',  desc: '5 members',          scope: 'visible across Finance Copilot' },
    { id: 'support-platform', kind: 'team',    name: 'Support Platform', desc: '12 members',         scope: 'visible across Support Platform' }
  ];

  function currentWorkspace() {
    var id = 'sandbox';
    try { var s = localStorage.getItem('aibc-workspace'); if (s) id = s; } catch (e) {}
    var match = WORKSPACES.filter(function (w) { return w.id === id; })[0];
    return match || WORKSPACES[0];
  }
  function wsIcon(w) { return ICON[w.kind === 'sandbox' ? 'sandbox' : 'team']; }

  var SUB_APPS = [
    { slug: 'persona-lab',         label: 'Persona Lab' },
    { slug: 'question-generation', label: 'Question Generation' },
    { slug: 'simulation',          label: 'Simulation' },
    { slug: 'evaluation',          label: 'Evaluation' },
    { slug: 'observability',       label: 'Observability' },
    { slug: 'self-heal',           label: 'Self-Heal' }
  ];
  var isStage = SUB_APPS.some(function (s) { return s.slug === activeSub; });

  // Governance context bar — one consistent tenant · env · spend strip on every
  // stage. Tenant + env are the same pre-release evaluation scope across the
  // product; the 24h spend is a per-stage (synthetic) LLM + judge cost figure.
  var SCOPE_TENANT = 'acme-corp';
  var SCOPE_ENV    = 'pre-release';
  var SCOPE_SPEND  = {
    'persona-lab':         '$0.80',
    'question-generation': '$3.10',
    'simulation':          '$6.90',
    'evaluation':          '$9.20',
    'observability':       '$12.40',
    'self-heal':           '$4.60'
  };

  var SECTION_LANDING  = new URL('index.html', sectionUrl).href;
  var SETTINGS_LANDING = new URL('settings.html', sectionUrl).href;
  var APPS_LANDING     = new URL('index.html', appsUrl).href;
  var HOME             = new URL('index.html', repoUrl).href;

  var CSS = [
    'html.aibc-chrome .mock-back { display: none !important; }',
    'html.aibc-chrome #aibc-theme-toggle[data-aibc-theme-injected] { display: none !important; }',
    // The per-page sub-brand strip (header.top) restates the AIBuilderCore brand,
    // the framework name, and the sub-app name — all already carried by the
    // injected top bar + left rail. Hide it so pages open clean.
    'html.aibc-chrome header.top { display: none !important; }',
    // Footers lead with a repo filepath breadcrumb — dev noise. Drop it.
    'html.aibc-chrome .foot > span:first-child { display: none !important; }',
    'html.aibc-chrome body { background: var(--bg); color: var(--text); }',

    /* ── Top bar ──────────────────────────────────────────────────────── */
    '.aibc-site-header {',
    '  position: sticky; top: 0; z-index: 60;',
    '  height: 56px; display: flex; align-items: center;',
    '  background: var(--bg);',
    '  border-bottom: 1px solid var(--border);',
    '}',
    '.aibc-site-header__inner {',
    '  width: 100%; max-width: 1480px; margin: 0 auto;',
    '  padding: 0 clamp(1rem, 3vw, 2rem);',
    '  display: flex; align-items: center; gap: 0.9rem;',
    '}',
    '.aibc-crumbs { display: flex; align-items: center; gap: 0.55rem; min-width: 0; }',
    '.aibc-brand {',
    '  display: inline-flex; align-items: center; gap: 0.55rem; flex-shrink: 0;',
    "  font-family: 'Space Grotesk', 'Geist', 'Inter', sans-serif;",
    '  font-size: 15px; font-weight: 600;',
    '  color: var(--text); text-decoration: none; letter-spacing: -0.01em;',
    '}',
    '.aibc-brand:hover { color: var(--accent); }',
    '.aibc-brand__dot {',
    '  width: 8px; height: 8px; border-radius: 999px;',
    '  background: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft);',
    '}',
    '.aibc-crumb-sep { color: var(--text-faint); font-size: 13px; flex-shrink: 0; }',
    '.aibc-crumb {',
    '  color: var(--text-muted); font-size: 14px; text-decoration: none;',
    '  white-space: nowrap; transition: color 150ms ease;',
    '}',
    '.aibc-crumb:hover { color: var(--text); }',
    '.aibc-header-right {',
    '  margin-left: auto; flex-shrink: 0;',
    '  display: inline-flex; align-items: center; gap: 0.6rem;',
    '}',
    '.aibc-chrome-toggle {',
    '  display: inline-flex; align-items: center; justify-content: center;',
    '  width: 32px; height: 32px; padding: 0; flex-shrink: 0;',
    '  background: transparent; border: 1px solid var(--border); border-radius: 8px;',
    '  color: var(--text-muted); cursor: pointer;',
    '  transition: color 150ms ease, background-color 150ms ease, border-color 150ms ease;',
    '}',
    '.aibc-chrome-toggle:hover { color: var(--text); background: var(--surface-alt); border-color: var(--border-strong); }',
    '.aibc-chrome-toggle__icon { width: 16px; height: 16px; }',
    '.aibc-chrome-chips { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; }',
    '.aibc-chrome-chip {',
    '  display: inline-flex; align-items: baseline; gap: 6px;',
    "  font-family: 'JetBrains Mono', ui-monospace, monospace;",
    '  font-size: 11.5px; color: var(--text-muted);',
    '  padding: 5px 10px; border: 1px solid var(--border);',
    '  border-radius: 999px; background: var(--surface); white-space: nowrap;',
    '}',
    '.aibc-chrome-chip__label { text-transform: uppercase; letter-spacing: 0.08em; font-size: 9.5px; color: var(--text-faint); }',
    '.aibc-chrome-chip__value { color: var(--text); font-weight: 500; }',
    '.aibc-chrome-chip__caret { color: var(--text-faint); font-size: 10px; }',
    '.aibc-chrome-chip--spend .aibc-chrome-chip__value { color: var(--accent); }',
    '@media (max-width: 980px) { .aibc-chrome-chip--tenant, .aibc-chrome-chip--env { display: none; } }',
    '@media (max-width: 700px) { .aibc-chrome-chips { display: none; } }',

    /* ── App shell + left rail ────────────────────────────────────────── */
    '.aibc-shell {',
    '  display: grid; grid-template-columns: 248px minmax(0, 1fr);',
    '  max-width: 1480px; margin: 0 auto; align-items: start;',
    '}',
    '.aibc-sidebar {',
    '  position: sticky; top: 56px;',
    '  height: calc(100vh - 56px);',
    '  display: flex; flex-direction: column;',
    '  background: var(--bg); border-right: 1px solid var(--border);',
    '}',
    '.aibc-sidebar__scroll {',
    '  flex: 1 1 auto; overflow-y: auto;',
    '  padding: 1.25rem 0.8rem 1rem; scrollbar-gutter: stable;',
    '}',
    '.aibc-sidebar__scroll::-webkit-scrollbar { width: 8px; }',
    '.aibc-sidebar__scroll::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }',
    '.aibc-sidebar__scroll::-webkit-scrollbar-track { background: transparent; }',
    '.aibc-sidebar__eyebrow {',
    "  font-family: 'Space Grotesk', 'Geist', sans-serif;",
    '  text-transform: uppercase; letter-spacing: 0.08em;',
    '  font-size: 10px; font-weight: 600; color: var(--text-faint);',
    '  padding: 0 0.7rem; margin: 0 0 0.3rem;',
    '}',
    '.aibc-sidebar__title {',
    '  display: block; padding: 0.35rem 0.7rem; margin: 0 0 0.9rem;',
    "  font-family: 'Space Grotesk', 'Geist', sans-serif;",
    '  font-size: 15px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.25;',
    '  color: var(--text); text-decoration: none;',
    '  border-radius: 8px; transition: color 150ms ease, background-color 150ms ease;',
    '}',
    '.aibc-sidebar__title:hover { background: var(--surface-alt); }',
    '.aibc-sidebar__title.is-active { color: var(--accent); background: var(--accent-soft); }',
    '.aibc-sidebar__heading {',
    "  font-family: 'JetBrains Mono', ui-monospace, monospace;",
    '  text-transform: uppercase; letter-spacing: 0.1em;',
    '  font-size: 9.5px; font-weight: 500; color: var(--text-faint);',
    '  padding: 0 0.7rem; margin: 0.2rem 0 0.35rem;',
    '}',
    '.aibc-nav-link {',
    '  display: flex; align-items: center; gap: 0.6rem;',
    '  padding: 0.5rem 0.7rem; margin: 1px 0;',
    '  color: var(--text-muted); text-decoration: none;',
    '  border-radius: 8px; font-size: 13.5px; font-weight: 500;',
    '  transition: color 150ms ease, background-color 150ms ease;',
    '}',
    '.aibc-nav-link:hover { color: var(--text); background: var(--surface-alt); }',
    '.aibc-nav-link.is-active { color: var(--accent); background: var(--accent-soft); font-weight: 600; }',
    '.aibc-nav-link__icon {',
    '  width: 16px; height: 16px; flex-shrink: 0; color: var(--text-faint);',
    '}',
    '.aibc-nav-link:hover .aibc-nav-link__icon { color: var(--text-muted); }',
    '.aibc-nav-link.is-active .aibc-nav-link__icon { color: var(--accent); }',
    '.aibc-nav-link__icon svg { width: 100%; height: 100%; display: block; }',

    /* pinned foot — user + settings */
    '.aibc-sidebar__foot {',
    '  flex-shrink: 0; border-top: 1px solid var(--border);',
    '  padding: 0.6rem 0.8rem 0.75rem;',
    '}',
    '.aibc-user {',
    '  display: flex; align-items: center; gap: 0.6rem; width: 100%;',
    '  padding: 0.45rem 0.6rem; margin-bottom: 0.15rem;',
    '  background: transparent; border: 1px solid transparent; border-radius: 10px;',
    '  text-align: left; cursor: pointer; color: inherit;',
    '  transition: background-color 150ms ease, border-color 150ms ease;',
    '}',
    '.aibc-user:hover { background: var(--surface-alt); border-color: var(--border); }',
    '.aibc-user__avatar {',
    '  width: 30px; height: 30px; flex-shrink: 0; border-radius: 999px;',
    '  display: inline-flex; align-items: center; justify-content: center;',
    "  font-family: 'Space Grotesk', 'Geist', sans-serif;",
    '  font-size: 11.5px; font-weight: 600; letter-spacing: 0.02em;',
    '  color: var(--accent); background: var(--accent-soft);',
    '  box-shadow: inset 0 0 0 1px var(--border);',
    '}',
    '.aibc-user__meta { min-width: 0; display: flex; flex-direction: column; line-height: 1.25; }',
    '.aibc-user__name { font-size: 13px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '.aibc-user__sub { font-size: 10.5px; color: var(--text-faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '.aibc-user__caret { margin-left: auto; color: var(--text-faint); font-size: 10px; flex-shrink: 0; }',
    '.aibc-user__name { display: inline-flex; align-items: center; gap: 5px; }',
    '.aibc-user__badge {',
    "  font-family: 'JetBrains Mono', ui-monospace, monospace;",
    '  font-size: 8.5px; font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase;',
    '  color: var(--accent); background: var(--accent-soft);',
    '  padding: 1px 5px; border-radius: 999px;',
    '}',

    /* ── Workspace switcher (top of sidebar) ──────────────────────────── */
    '.aibc-sidebar__head { flex-shrink: 0; padding: 0.7rem 0.7rem 0.65rem; border-bottom: 1px solid var(--border); }',
    '.aibc-ws { position: relative; }',
    '.aibc-ws__btn {',
    '  display: flex; align-items: center; gap: 0.55rem; width: 100%;',
    '  padding: 0.45rem 0.55rem; background: var(--surface);',
    '  border: 1px solid var(--border); border-radius: 10px;',
    '  cursor: pointer; color: inherit; text-align: left;',
    '  transition: border-color 150ms ease, background-color 150ms ease;',
    '}',
    '.aibc-ws__btn:hover { border-color: var(--border-strong); background: var(--surface-alt); }',
    '.aibc-ws__btn[aria-expanded="true"] { border-color: var(--accent); }',
    '.aibc-ws__icon {',
    '  width: 28px; height: 28px; flex-shrink: 0; border-radius: 8px;',
    '  display: inline-flex; align-items: center; justify-content: center;',
    '  color: var(--accent); background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--border);',
    '}',
    '.aibc-ws__icon svg { width: 15px; height: 15px; }',
    '.aibc-ws__meta { min-width: 0; display: flex; flex-direction: column; line-height: 1.2; }',
    '.aibc-ws__eyebrow {',
    "  font-family: 'JetBrains Mono', ui-monospace, monospace;",
    '  font-size: 8.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-faint);',
    '}',
    '.aibc-ws__label { font-size: 13px; font-weight: 600; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '.aibc-ws__caret { margin-left: auto; color: var(--text-faint); font-size: 10px; flex-shrink: 0; }',
    '.aibc-ws__menu {',
    '  position: absolute; z-index: 70; top: calc(100% + 6px); left: 0; right: 0;',
    '  background: var(--surface); border: 1px solid var(--border-strong);',
    '  border-radius: 12px; box-shadow: 0 14px 34px var(--shadow-strong); padding: 0.35rem;',
    '}',
    '.aibc-ws__menu[hidden] { display: none; }',
    '.aibc-ws__group {',
    "  font-family: 'JetBrains Mono', ui-monospace, monospace;",
    '  font-size: 9px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-faint);',
    '  padding: 0.4rem 0.5rem 0.2rem; margin: 0;',
    '}',
    '.aibc-ws__opt {',
    '  display: flex; align-items: center; gap: 0.55rem; width: 100%;',
    '  padding: 0.45rem 0.5rem; background: transparent; border: 0; border-radius: 8px;',
    '  cursor: pointer; color: inherit; text-align: left;',
    '}',
    '.aibc-ws__opt:hover { background: var(--surface-alt); }',
    '.aibc-ws__opt-icon {',
    '  width: 26px; height: 26px; flex-shrink: 0; border-radius: 7px;',
    '  display: inline-flex; align-items: center; justify-content: center;',
    '  color: var(--text-muted); background: var(--surface-alt);',
    '}',
    '.aibc-ws__opt-icon svg { width: 14px; height: 14px; }',
    '.aibc-ws__opt.is-selected .aibc-ws__opt-icon { color: var(--accent); background: var(--accent-soft); }',
    '.aibc-ws__opt-meta { min-width: 0; display: flex; flex-direction: column; line-height: 1.2; }',
    '.aibc-ws__opt-name { font-size: 13px; font-weight: 500; color: var(--text); }',
    '.aibc-ws__opt-desc { font-size: 10.5px; color: var(--text-faint); }',
    '.aibc-ws__opt-check { margin-left: auto; width: 16px; height: 16px; flex-shrink: 0; color: var(--accent); opacity: 0; }',
    '.aibc-ws__opt-check svg { width: 16px; height: 16px; }',
    '.aibc-ws__opt.is-selected .aibc-ws__opt-check { opacity: 1; }',
    '.aibc-ws__foot {',
    '  margin: 0.2rem 0.15rem 0.1rem; padding: 0.45rem 0.5rem 0.15rem;',
    '  border-top: 1px solid var(--border);',
    '  font-size: 10.5px; line-height: 1.4; color: var(--text-faint);',
    '}',

    '@media (max-width: 860px) {',
    '  .aibc-shell { grid-template-columns: 1fr; }',
    '  .aibc-sidebar { position: static; height: auto; border-right: none; border-bottom: 1px solid var(--border); }',
    '  .aibc-sidebar__scroll { padding-bottom: 0.5rem; }',
    '}',

    '.aibc-main { min-width: 0; }'
  ].join('\n');

  var MOON_SVG = '<svg class="aibc-chrome-toggle__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  var SUN_SVG = '<svg class="aibc-chrome-toggle__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.6"/>' +
    '<path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>';

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
    });
  }

  function buildChips() {
    if (!isStage) return '';  // Dashboard / Settings carry their own context
    // Static fallback; hydrateSpend() replaces this with the real derived figure
    // from /observability/spend once the API client is present.
    var spend = SCOPE_SPEND[activeSub] || '$0.00';
    return [
      '<div class="aibc-chrome-chips" role="group" aria-label="Scope">',
      '  <span class="aibc-chrome-chip aibc-chrome-chip--tenant" title="Tenant scope (stub)">',
      '    <span class="aibc-chrome-chip__label">tenant</span>',
      '    <span class="aibc-chrome-chip__value">' + escapeHtml(SCOPE_TENANT) + '</span>',
      '    <span class="aibc-chrome-chip__caret" aria-hidden="true">▾</span>',
      '  </span>',
      '  <span class="aibc-chrome-chip aibc-chrome-chip--env" title="Environment: pre-release evaluation (not live production)">',
      '    <span class="aibc-chrome-chip__label">env</span>',
      '    <span class="aibc-chrome-chip__value">' + escapeHtml(SCOPE_ENV) + '</span>',
      '    <span class="aibc-chrome-chip__caret" aria-hidden="true">▾</span>',
      '  </span>',
      '  <span class="aibc-chrome-chip aibc-chrome-chip--spend" title="LLM + judge spend for this stage (last 24h)">',
      '    <span class="aibc-chrome-chip__label">spend 24h</span>',
      '    <span class="aibc-chrome-chip__value" id="aibc-chrome-spend">' + escapeHtml(spend) + '</span>',
      '  </span>',
      '</div>'
    ].join('\n');
  }

  function buildHeader() {
    return [
      '<div class="aibc-site-header__inner">',
      '  <nav class="aibc-crumbs" aria-label="Breadcrumb">',
      '    <a class="aibc-brand" href="' + HOME + '">',
      '      <span class="aibc-brand__dot" aria-hidden="true"></span>',
      '      <span>AIBuilderCore</span>',
      '    </a>',
      '    <span class="aibc-crumb-sep" aria-hidden="true">/</span>',
      '    <a class="aibc-crumb" href="' + APPS_LANDING + '">Applications</a>',
      '  </nav>',
      '  <div class="aibc-header-right">',
      '    ' + buildChips(),
      '    <button id="aibc-chrome-theme" class="aibc-chrome-toggle" type="button" aria-label="Toggle theme" title="Toggle theme">',
      '      <span class="aibc-chrome-toggle__moon">' + MOON_SVG + '</span>',
      '      <span class="aibc-chrome-toggle__sun" style="display:none;">' + SUN_SVG + '</span>',
      '    </button>',
      '  </div>',
      '</div>'
    ].join('\n');
  }

  function buildWorkspaceSwitcher() {
    var cur = currentWorkspace();
    var opts = '', lastKind = '';
    WORKSPACES.forEach(function (w) {
      if (w.kind !== lastKind) {
        opts += '<p class="aibc-ws__group">' + (w.kind === 'sandbox' ? 'Personal' : 'Your teams') + '</p>';
        lastKind = w.kind;
      }
      var sel = w.id === cur.id ? ' is-selected' : '';
      opts +=
        '<button type="button" role="option" class="aibc-ws__opt' + sel + '" data-ws="' + w.id + '" aria-selected="' + (w.id === cur.id) + '">' +
        '<span class="aibc-ws__opt-icon" aria-hidden="true">' + wsIcon(w) + '</span>' +
        '<span class="aibc-ws__opt-meta"><span class="aibc-ws__opt-name">' + escapeHtml(w.name) + '</span>' +
        '<span class="aibc-ws__opt-desc">' + escapeHtml(w.desc) + '</span></span>' +
        '<span class="aibc-ws__opt-check" aria-hidden="true">' + ICON.check + '</span></button>';
    });
    return [
      '<div class="aibc-ws" data-aibc-ws>',
      '  <button type="button" class="aibc-ws__btn" aria-haspopup="listbox" aria-expanded="false">',
      '    <span class="aibc-ws__icon" data-ws-btn-icon aria-hidden="true">' + wsIcon(cur) + '</span>',
      '    <span class="aibc-ws__meta">',
      '      <span class="aibc-ws__eyebrow">Workspace</span>',
      '      <span class="aibc-ws__label" data-ws-btn-label>' + escapeHtml(cur.name) + '</span>',
      '    </span>',
      '    <span class="aibc-ws__caret" aria-hidden="true">▾</span>',
      '  </button>',
      '  <div class="aibc-ws__menu" role="listbox" aria-label="Switch workspace" hidden>',
      opts,
      '    <p class="aibc-ws__foot">Artifacts are scoped to the selected workspace across all five stages.</p>',
      '  </div>',
      '</div>'
    ].join('\n');
  }

  function buildSidebar() {
    function navLink(href, iconKey, label, active) {
      return '<a href="' + href + '" class="aibc-nav-link' + (active ? ' is-active' : '') + '">' +
        '<span class="aibc-nav-link__icon" aria-hidden="true">' + (ICON[iconKey] || '') + '</span>' +
        '<span>' + escapeHtml(label) + '</span></a>';
    }

    var head = '<div class="aibc-sidebar__head">' + buildWorkspaceSwitcher() + '</div>';

    var links = [navLink(SECTION_LANDING, 'dashboard', 'Dashboard', !activeSub)];
    SUB_APPS.forEach(function (s) {
      var url = new URL(s.slug + '/index.html', sectionUrl).href;
      links.push(navLink(url, s.slug, s.label, s.slug === activeSub && !isCatalog));
      // Judge Catalogue sits directly under Evaluation — the sync judge registry.
      if (s.slug === 'evaluation') {
        var catUrl = new URL('evaluation/catalog.html', sectionUrl).href;
        links.push(navLink(catUrl, 'judges', 'Judge Catalogue', isCatalog));
      }
    });
    var scroll = '<div class="aibc-sidebar__scroll">' + links.join('\n') + '</div>';

    var settingsCls = 'aibc-nav-link aibc-settings' + (isSettings ? ' is-active' : '');
    var foot = [
      '<div class="aibc-sidebar__foot">',
      '  <button type="button" class="aibc-user" title="Account (demo)">',
      '    <span class="aibc-user__avatar" aria-hidden="true">' + escapeHtml(USER.initials) + '</span>',
      '    <span class="aibc-user__meta">',
      '      <span class="aibc-user__name">' + escapeHtml(USER.name) +
      (USER.admin ? ' <span class="aibc-user__badge">admin</span>' : '') + '</span>',
      '      <span class="aibc-user__sub">' + escapeHtml(USER.role + ' · ' + USER.tenant) + '</span>',
      '    </span>',
      '    <span class="aibc-user__caret" aria-hidden="true">▾</span>',
      '  </button>',
      '  <a href="' + SETTINGS_LANDING + '" class="' + settingsCls + '">',
      '    <span class="aibc-nav-link__icon" aria-hidden="true">' + ICON.settings + '</span>',
      '    <span>Settings</span></a>',
      '</div>'
    ].join('\n');

    return head + '\n' + scroll + '\n' + foot;
  }

  function wireThemeToggle() {
    var btn = document.getElementById('aibc-chrome-theme');
    if (!btn) return;
    var moon = btn.querySelector('.aibc-chrome-toggle__moon');
    var sun  = btn.querySelector('.aibc-chrome-toggle__sun');

    function isDark() {
      var attr = document.documentElement.getAttribute('data-theme');
      if (attr === 'dark') return true;
      if (attr === 'light') return false;
      return window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    function paint() {
      var dark = isDark();
      moon.style.display = dark ? 'none' : 'block';
      sun.style.display  = dark ? 'block' : 'none';
    }
    paint();
    btn.addEventListener('click', function () {
      var next = isDark() ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('aibc-theme', next); } catch (e) {}
      paint();
    });
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', paint);
    else if (mq.addListener) mq.addListener(paint);
  }

  function applyWorkspace(w) {
    var root = document.documentElement;
    root.setAttribute('data-workspace', w.id);
    root.setAttribute('data-workspace-kind', w.kind);
    var lbl = document.querySelector('[data-ws-btn-label]');
    if (lbl) lbl.textContent = w.name;
    var ico = document.querySelector('[data-ws-btn-icon]');
    if (ico) ico.innerHTML = wsIcon(w);
    // Page-level hooks so hand-authored pages (e.g. the dashboard) can reflect
    // the active scope without knowing the workspace list.
    Array.prototype.forEach.call(document.querySelectorAll('[data-ws-name]'), function (el) { el.textContent = w.name; });
    Array.prototype.forEach.call(document.querySelectorAll('[data-ws-scope]'), function (el) { el.textContent = w.scope; });
  }

  function wireWorkspaceSwitcher() {
    var root = document.querySelector('[data-aibc-ws]');
    if (!root) return;
    var btn = root.querySelector('.aibc-ws__btn');
    var menu = root.querySelector('.aibc-ws__menu');

    function onDoc(e) { if (!root.contains(e.target)) close(); }
    function onKey(e) { if (e.key === 'Escape') { close(); btn.focus(); } }
    function open() {
      menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
      document.addEventListener('mousedown', onDoc);
      document.addEventListener('keydown', onKey);
    }
    function close() {
      menu.hidden = true; btn.setAttribute('aria-expanded', 'false');
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    }
    btn.addEventListener('click', function () { menu.hidden ? open() : close(); });
    menu.addEventListener('click', function (e) {
      var opt = e.target.closest && e.target.closest('[data-ws]');
      if (!opt) return;
      var id = opt.getAttribute('data-ws');
      var w = WORKSPACES.filter(function (x) { return x.id === id; })[0];
      if (!w) return;
      try { localStorage.setItem('aibc-workspace', id); } catch (err) {}
      Array.prototype.forEach.call(menu.querySelectorAll('.aibc-ws__opt'), function (o) {
        var on = o === opt;
        o.classList.toggle('is-selected', on);
        o.setAttribute('aria-selected', on);
      });
      applyWorkspace(w);
      close();
    });
    applyWorkspace(currentWorkspace());
  }

  function init() {
    if (document.documentElement.classList.contains('aibc-chrome')) return;
    document.documentElement.classList.add('aibc-chrome');

    // Shared design-system layer. Appended after the sub-app's own styles.css
    // so its rules win ties and enforce one consistent look.
    var appCss = document.createElement('link');
    appCss.rel = 'stylesheet';
    appCss.href = new URL('_app.css', scriptUrl).href;
    appCss.setAttribute('data-aibc-app', '');
    document.head.appendChild(appCss);

    var styleEl = document.createElement('style');
    styleEl.setAttribute('data-aibc-chrome', '');
    styleEl.textContent = CSS;
    document.head.appendChild(styleEl);

    var header = document.createElement('header');
    header.className = 'aibc-site-header';
    header.innerHTML = buildHeader();

    var sidebar = document.createElement('aside');
    sidebar.className = 'aibc-sidebar';
    sidebar.setAttribute('aria-label', 'Application navigation');
    sidebar.innerHTML = buildSidebar();

    var main = document.createElement('div');
    main.className = 'aibc-main';
    while (document.body.firstChild) {
      main.appendChild(document.body.firstChild);
    }

    var shell = document.createElement('div');
    shell.className = 'aibc-shell';
    shell.appendChild(sidebar);
    shell.appendChild(main);

    document.body.appendChild(header);
    document.body.appendChild(shell);

    wireThemeToggle();
    wireWorkspaceSwitcher();
    hydrateSpend();
  }

  // Replace the static per-stage spend chip with the real derived figure from
  // /observability/spend (the same rollup the dashboard uses), so the header
  // never shows a fabricated cost. Silent no-op when the API client is absent.
  function hydrateSpend() {
    if (!isStage || !window.EEOF || typeof EEOF.get !== 'function') return;
    var el = document.getElementById('aibc-chrome-spend');
    if (!el) return;
    EEOF.get('/observability/spend').then(function (data) {
      var stages = (data && data.stages) || [];
      var stage = stages.filter(function (s) { return s.slug === activeSub; })[0];
      if (stage && typeof stage.amount === 'number') {
        el.textContent = '$' + stage.amount.toFixed(2);
      }
    }).catch(function () {});
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
