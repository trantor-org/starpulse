// Mockup layer (TASK-2657): editing and archiving a task from the Kanban task modal, injected over a capture of the live page.
// The board writer is simulated, refusals included: a save is one `update` call, all or nothing; an archive is one `archive` call.
(() => {
  const STATES = {
    kanban: {},
    edit: { open: "ready", edit: true },
    "edit-evidence": { open: "ready", edit: true, evidence: true },
    "edit-refused": { open: "ready", edit: true, refuse: true },
    archive: { open: "waiting", archive: true },
    "archive-warn": { open: "pr", archive: true },
    "archive-refused": { open: "waiting", archive: true, archiveRefuse: true },
    archived: { open: "waiting", archive: true, confirm: true },
  };
  const qs = new URLSearchParams(location.search);
  const preset = STATES[qs.get("s")] || STATES[location.hash.slice(1)] || null;
  {
    const p = new URLSearchParams(location.search);
    p.set("view", "kanban");
    p.delete("s");
    try { history.replaceState(null, "", location.pathname + "?" + p.toString() + location.hash); } catch {}
  }

  // ---- the task records the writer would hold: what the snapshot carries plus the fields only the task file has ----
  const fixture = () => window.__FLOW_FIXTURE__ || {};
  const agents = () => (fixture().flows || [])[0]?.agents || [];
  const PROFILES = ["@agent-light-low", "@agent-standard-medium", "@agent-standard-high", "@agent-deep-high", "@agent-deep-xhigh"];
  const PRIORITIES = ["High", "Medium", "Low"];
  const records = new Map();
  function record(id) {
    if (records.has(id)) return records.get(id);
    const a = agents().find((x) => x.id === id);
    if (!a) return null;
    const n = +id.replace(/\D/g, "") || 1;
    const r = {
      id, title: a.title, state: a.state, assignee: a.model || "", priority: PRIORITIES[n % 3], milestone: a.milestone || "",
      labels: [...a.labels], dependencies: [...a.dependencies],
      description: a.description || "",
      plan: `1. Read the code behind "${a.title}" and its tests.\n2. Write the failing test.\n3. Make the smallest change that passes.\n4. Update the service doc.`,
      notes: n % 2 ? "" : "Checked against the live config on ai-vm-1; the old default is still read by one caller.",
      ac: [
        { text: `A test that failed first covers "${a.title}"`, checked: a.state === "done" || a.state === "review" },
        { text: "make lint-changed passes", checked: a.state === "done" || a.state === "review" },
        { text: "The service doc names the new behaviour", checked: a.state === "done" },
      ],
      dod: [
        { text: "Implementation Notes and the final summary reflect the delivered state", checked: a.state === "done" },
        { text: "The completing-tasks skill was invoked before task closure", checked: a.state === "done" },
      ],
      pr: (fixture().pulls || {})[id]?.[0] || null,
    };
    records.set(id, r);
    return r;
  }
  const clone = (r) => JSON.parse(JSON.stringify(r));
  const milestones = () => [...new Set(agents().map((a) => a.milestone).filter(Boolean))].sort((a, b) => +b.slice(2) - +a.slice(2));
  const allLabels = () => [...new Set(agents().flatMap((a) => a.labels))].sort();

  // ---- styles, in the page's own tokens ----
  const css = `
  #kbm .modal.tvmode:not(.ask) { display: flex; flex-direction: column; padding: 0; overflow: hidden; max-height: min(86vh, 860px); }
  #kbm .modal.tvmode:not(.ask) > :not(.tv):not(.x) { display: none !important; }
  #kbm .modal.ask > .tv { display: none; }
  #kbm .tv { display: flex; flex-direction: column; flex: 1; min-height: 0; }
  #kbm .tvhead { flex: none; display: flex; align-items: flex-start; gap: 16px; padding: 18px 54px 14px 26px; border-bottom: 1px solid rgba(148,163,184,.12); }
  #kbm .tvhead .ttl { flex: 1; min-width: 0; }
  #kbm .tvhead .k a { color: #a78bfa; text-decoration: none; } #kbm .tvhead .k a:hover { text-decoration: underline; }
  #kbm .tv .acts { flex: none; width: 300px; display: flex; justify-content: flex-end; align-items: center; gap: 8px; min-height: 30px; }
  #kbm .tv .acts .cnt { color: var(--muted); font-size: 11.5px; white-space: nowrap; } #kbm .tv .acts button { white-space: nowrap; } #kbm .tv .acts .cnt.on { color: #c4b5fd; } #kbm .tv .acts .cnt.disc { color: #fecaca; }
  #kbm .tvbody { overflow-y: auto; padding: 18px 26px 26px; display: flex; flex-direction: column; gap: 20px; scrollbar-width: thin; scrollbar-color: #94a3b840 transparent; }
  #kbm .tv table { margin-top: 0; }
  #kbm .tv td { vertical-align: middle; padding: 3px 14px 3px 0; }
  #kbm .tv td:first-child { width: 104px; }
  #kbm .tv tr.ro td:last-child { color: #b8c4d8; }
  #kbm .tv tr.dirty td:first-child::after, #kbm .tv .sec.dirty .sh .t::after { content: " •"; color: #c4b5fd; }
  #kbm .tv tr.bad td:first-child, #kbm .tv .sec.bad .sh { color: #fbbf24; }
  /* Move to lives in the fixed footer's right corner as one menu that opens upward over the body. */
  #kbm .tvfoot { flex: none; display: flex; justify-content: flex-end; align-items: center; padding: 10px 26px; border-top: 1px solid rgba(148,163,184,.12); }
  #kbm .tvfoot { gap: 8px; }
  #kbm .tvfoot .mv { position: relative; }
  #kbm .tvfoot .startbtn { all: unset; cursor: pointer; padding: 4px 12px; border-radius: 6px; border: 1px solid rgba(52,211,153,.55); background: rgba(52,211,153,.12); color: #a7f3d0; font-size: 11.5px; white-space: nowrap; }
  #kbm .tvfoot .startbtn:hover, #kbm .tvfoot .startbtn:focus-visible { background: rgba(52,211,153,.22); }
  #kbm .tvfoot .startbtn:disabled { opacity: .4; cursor: default; background: rgba(52,211,153,.12); }
  #kbm .tvfoot .mvbtn { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 8px; padding: 4px 10px 4px 12px; border-radius: 6px; border: 1px solid rgba(148,163,184,.3); color: #cbd5e1; font-size: 11.5px; }
  #kbm .tvfoot .mvbtn::after { content: ""; width: 5px; height: 5px; border: solid #6b7a93; border-width: 0 1.5px 1.5px 0; transform: translateY(1px) rotate(225deg); }
  #kbm .tvfoot .mvbtn[aria-expanded=false]::after { transform: translateY(-2px) rotate(45deg); }
  #kbm .tvfoot .mvbtn:hover, #kbm .tvfoot .mvbtn:focus-visible, #kbm .tvfoot .mvbtn[aria-expanded=true] { border-color: #a78bfa; background: rgba(167,139,250,.10); }
  #kbm .tvfoot .mvbtn:disabled { opacity: .4; cursor: default; background: none; border-color: rgba(148,163,184,.3); }
  #kbm .tvfoot .mvmenu { position: absolute; right: 0; bottom: calc(100% + 6px); z-index: 6; min-width: 200px; padding: 4px; background: #0c1322; border: 1px solid rgba(148,163,184,.3); border-radius: 8px; box-shadow: 0 10px 30px rgba(0,0,0,.5); }
  #kbm .tvfoot .mvmenu[hidden] { display: none; }
  #kbm .tvfoot .mvmenu div { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-radius: 5px; font-size: 12px; color: #cbd5e1; cursor: pointer; white-space: nowrap; }
  #kbm .tvfoot .mvmenu div.on { background: rgba(167,139,250,.16); color: #ede9fe; }
  #kbm .tvfoot .mvmenu div[aria-disabled=true] { opacity: .4; cursor: default; }
  #kbm .tvfoot .mvmenu .g { width: 14px; text-align: center; color: #6b7a93; }
  #kbm .tv .sec { display: flex; flex-direction: column; gap: 6px; }
  #kbm .tv .sh { display: flex; align-items: center; gap: 8px; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
  #kbm .tv .sh .n { letter-spacing: 0; }
  /* One control per field in both modes; read mode draws a faint shadow of its frame and refuses input, so nothing moves on Edit. */
  #kbm .tv .fv { box-sizing: border-box; width: calc(100% + 9px); margin: 0 0 0 -9px; font: inherit; line-height: 1.5; color: var(--ink); background: rgba(148,163,184,.03);
    border: 1px solid rgba(148,163,184,.10); border-radius: 6px; padding: 3px 8px; outline: none; opacity: 1; }
  #kbm .tv:not(.editing) .fv, #kbm .tv:not(.editing) .item input[type=checkbox] { pointer-events: none; }
  #kbm .tv.editing .fv { background: rgba(148,163,184,.06); border-color: rgba(148,163,184,.22); }
  #kbm .tv.editing .fv:focus, #kbm .tv.editing .fv:focus-within { border-color: #a78bfa; box-shadow: 0 0 0 2px rgba(167,139,250,.18); }
  #kbm .tv .fv::placeholder { color: #475569; }
  #kbm .tv textarea.fv.title { font-size: 16px; font-weight: 500; padding: 1px 8px; margin-bottom: 2px; color: var(--ink); }
  #kbm .tv select.fv { appearance: none; width: auto; min-width: 240px; padding-right: 26px; }
  #kbm .tv.editing select.fv { background-image: linear-gradient(45deg, transparent 50%, #6b7a93 50%), linear-gradient(135deg, #6b7a93 50%, transparent 50%);
    background-position: calc(100% - 13px) 50%, calc(100% - 9px) 50%; background-size: 4px 4px; background-repeat: no-repeat; }
  #kbm .tv select option { background: #0c1322; }
  #kbm .tv textarea.fv { display: block; resize: none; overflow: hidden; white-space: pre-wrap; color: #b8c4d8; }
  /* Plan and notes keep a fixed taller box in both modes and scroll inside it rather than growing. */
  #kbm .tv textarea.fv.long { height: 152px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: #94a3b840 transparent; }
  #kbm .tv:not(.editing) textarea.fv.long { pointer-events: auto; cursor: default; }
  #kbm .tv .fv.chips { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; min-height: 30px; position: relative; }
  #kbm .tv .chip { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 10px; background: rgba(148,163,184,.12); color: #cbd5e1; font-size: 11.5px; }
  #kbm .tv.editing .chip { padding-right: 4px; }
  #kbm .tv .chip.nh { background: rgba(251,191,36,.14); color: #fcd34d; } #kbm .tv .chip.new { box-shadow: 0 0 0 1px rgba(167,139,250,.6); }
  #kbm .tv .chip button { all: unset; cursor: pointer; padding: 0 4px; color: #6b7a93; } #kbm .tv .chip button:hover, #kbm .tv .chip button:focus-visible { color: #f87171; }
  #kbm .tv .chips .ci { all: unset; flex: 1; min-width: 80px; font-size: 12px; color: var(--ink); padding: 1px 2px; }
  #kbm .tv .chips .none { color: #475569; }
  #kbm .tv:not(.editing) .chip button, #kbm .tv:not(.editing) .chips .ci, #kbm .tv.editing .chips .none { display: none; }
  #kbm .tv tr.bad .fv { border-color: rgba(251,191,36,.7); }
  #kbm .tv .sugg { position: absolute; left: 0; top: calc(100% + 4px); z-index: 5; min-width: 240px; background: #0c1322; border: 1px solid rgba(148,163,184,.3); border-radius: 6px;
    box-shadow: 0 12px 30px rgba(0,0,0,.5); padding: 4px; font-size: 12px; }
  #kbm .tv .sugg div { padding: 4px 8px; border-radius: 4px; cursor: pointer; color: #cbd5e1; display: flex; gap: 8px; } #kbm .tv .sugg div span { color: var(--muted); margin-left: auto; }
  #kbm .tv .sugg div.on, #kbm .tv .sugg div:hover { background: rgba(167,139,250,.16); }
  #kbm .tv .list { display: flex; flex-direction: column; gap: 2px; }
  #kbm .tv .item { display: grid; grid-template-columns: 22px 1fr 22px; align-items: center; gap: 4px; }
  #kbm .tv .item .fv { width: 100%; margin: 0; }
  /* Checkboxes draw the same box in both modes; editing only adds hover and focus. */
  #kbm .tv .item input[type=checkbox] { appearance: none; box-sizing: border-box; width: 16px; height: 16px; margin: 0 4px 0 0; border-radius: 4px; border: 1.5px solid rgba(148,163,184,.45); background: rgba(148,163,184,.04) center / 11px 11px no-repeat; cursor: pointer; transition: background-color .12s, border-color .12s; }
  #kbm .tv .item input[type=checkbox]:checked { border-color: #34d399; background-color: rgba(52,211,153,.18);
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='M2.5 6.2l2.3 2.3 4.7-5' fill='none' stroke='%236ee7b7' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"); }
  #kbm .tv.editing .item input[type=checkbox]:hover { border-color: #6ee7b7; }
  #kbm .tv .item input[type=checkbox]:focus-visible { outline: none; box-shadow: 0 0 0 2px rgba(110,231,183,.35); }
  #kbm .tv .item.done .fv { color: #94a3b8; }
  #kbm .tv .item .rm { all: unset; cursor: pointer; color: #6b7a93; text-align: center; } #kbm .tv .item .rm:hover, #kbm .tv .item .rm:focus-visible { color: #f87171; }
  #kbm .tv:not(.editing) .item .rm, #kbm .tv:not(.editing) .add { visibility: hidden; }
  #kbm .tv .ev { grid-column: 2 / 4; display: flex; flex-direction: column; gap: 4px; padding: 6px 8px; border-left: 2px solid #34d399; background: rgba(52,211,153,.06); border-radius: 0 6px 6px 0; }
  #kbm .tv .ev textarea { box-sizing: border-box; width: 100%; min-height: 44px; resize: vertical; font: 12px/1.5 "JetBrains Mono", ui-monospace, monospace; color: var(--ink);
    background: rgba(148,163,184,.06); border: 1px solid rgba(148,163,184,.22); border-radius: 6px; padding: 5px 9px; outline: none; }
  #kbm .tv .ev .h { font-size: 11px; color: #6ee7b7; } #kbm .tv .ev.bad { border-left-color: #fbbf24; background: rgba(251,191,36,.07); } #kbm .tv .ev.bad .h { color: #fcd34d; }
  #kbm .tv .add { all: unset; cursor: pointer; margin-left: auto; font-size: 11px; letter-spacing: 0; text-transform: none; color: #a78bfa; } #kbm .tv .add:hover, #kbm .tv .add:focus-visible { text-decoration: underline; }
  #kbm .tv .saved { padding: 6px 10px; border-radius: 6px; background: rgba(52,211,153,.08); border: 1px solid rgba(52,211,153,.3); color: #6ee7b7; font-size: 11.5px; }
  #kbm .tv .refused { padding: 8px 12px; border-radius: 6px; border: 1px solid rgba(251,191,36,.45); background: rgba(251,191,36,.08); color: #fcd34d; font-size: 12px; }
  #kbm .tv .refused .k2 { color: #94a3b8; font-size: 11px; margin-top: 2px; } #kbm .tv .refused b { font-weight: 500; }
  #kbm .tv .archbtn { all: unset; cursor: pointer; padding: 4px 10px; border-radius: 6px; border: 1px solid rgba(248,113,113,.4); color: #f87171; font-size: 11.5px; }
  #kbm .tv .archbtn:hover, #kbm .tv .archbtn:focus-visible { background: rgba(248,113,113,.10); }
  #kbm .tv .editbtn, #kbm .tv .savebtn { all: unset; cursor: pointer; padding: 4px 14px; border-radius: 6px; border: 1px solid rgba(167,139,250,.6); background: rgba(167,139,250,.16); color: #ede9fe; font-size: 11.5px; }
  #kbm .tv .editbtn:hover, #kbm .tv .editbtn:focus-visible, #kbm .tv .savebtn:hover, #kbm .tv .savebtn:focus-visible { background: rgba(167,139,250,.28); }
  #kbm .tv .savebtn:disabled { opacity: .4; cursor: default; }
  #kbm .tv .dangerbtn { all: unset; cursor: pointer; padding: 4px 14px; border-radius: 6px; border: 1px solid rgba(248,113,113,.6); background: rgba(248,113,113,.16); color: #fecaca; font-size: 11.5px; }
  #kbm .tv .spin { display: inline-block; width: 9px; height: 9px; border: 1.5px solid rgba(237,233,254,.35); border-top-color: #ede9fe; border-radius: 50%; animation: ef-spin .7s linear infinite; vertical-align: -1px; margin-right: 6px; }
  @keyframes ef-spin { to { transform: rotate(360deg); } }
  #efa { position: fixed; inset: 0; z-index: 60; display: flex; align-items: center; justify-content: center; background: rgba(2,4,10,.55); animation: kb-scrim .15s; }
  #efa .box { box-sizing: border-box; width: min(520px, calc(100vw - 40px)); padding: 20px 22px; border-radius: 12px; background: rgba(12,19,34,.99); border: 1px solid rgba(248,113,113,.35);
    box-shadow: 0 30px 80px rgba(0,0,0,.6); font-size: 12.5px; line-height: 1.6; color: var(--ink); animation: kb-modal .15s ease-out; display: flex; flex-direction: column; gap: 12px; }
  #efa h3 { margin: 0; font-size: 15px; font-weight: 500; } #efa .k { color: var(--muted); font-size: 11px; margin-top: -10px; }
  #efa .warn { display: flex; gap: 8px; padding: 7px 10px; border-radius: 6px; background: rgba(251,191,36,.08); border: 1px solid rgba(251,191,36,.35); color: #fcd34d; font-size: 12px; }
  #efa .warn .k3 { color: #94a3b8; font-size: 11px; display: block; }
  #efa .warn a { color: #a78bfa; text-decoration: none; }
  #efa label { display: flex; flex-direction: column; gap: 4px; font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); }
  #efa label i { letter-spacing: 0; text-transform: none; font-style: normal; }
  #efa textarea { box-sizing: border-box; width: 100%; min-height: 64px; resize: vertical; font: 12.5px/1.5 Inter, system-ui, sans-serif; color: var(--ink); background: rgba(148,163,184,.06);
    border: 1px solid rgba(148,163,184,.22); border-radius: 6px; padding: 6px 9px; outline: none; letter-spacing: 0; text-transform: none; }
  #efa textarea:focus { border-color: #f87171; box-shadow: 0 0 0 2px rgba(248,113,113,.15); }
  #efa .row { display: flex; gap: 10px; align-items: center; } #efa .row .sp { margin-left: auto; }
  #efa .row .hint { color: var(--muted); font-size: 11px; }
  #efa button { all: unset; cursor: pointer; padding: 5px 14px; border-radius: 6px; font-size: 12px; border: 1px solid rgba(148,163,184,.25); color: #94a3b8; }
  #efa button:hover, #efa button:focus-visible { color: var(--ink); border-color: rgba(148,163,184,.5); }
  #efa button.danger { border-color: rgba(248,113,113,.6); background: rgba(248,113,113,.16); color: #fecaca; }
  #efa button.danger:hover, #efa button.danger:focus-visible { background: rgba(248,113,113,.26); }
  #efa button:disabled { opacity: .45; cursor: default; }
  #efa .refused { padding: 7px 10px; border-radius: 6px; border: 1px solid rgba(248,113,113,.45); background: rgba(248,113,113,.08); color: #fca5a5; font-size: 12px; }
  #kb .c[data-ef-shown] { font-size: 0 !important; }
  #kb .c[data-ef-shown]::after { content: attr(data-ef-shown); font-size: var(--ef-fs); }
  .card.ef-arch { opacity: .45; outline: 1px dashed rgba(248,113,113,.6); }
  .card.ef-gone { animation: ef-gone .45s ease-in forwards; pointer-events: none; }
  @keyframes ef-gone { to { opacity: 0; transform: translateX(16px) scale(.96); } }
  .card .ef-note { margin-top: 6px; font-size: 11px; color: #fca5a5; display: flex; gap: 6px; } .card .ef-note button { all: unset; cursor: pointer; color: #94a3b8; margin-left: auto; }
  #ef-toast { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 70; padding: 8px 14px; border-radius: 8px; background: rgba(12,19,34,.98);
    border: 1px solid rgba(52,211,153,.4); color: #a7f3d0; font: 12px Inter, system-ui, sans-serif; box-shadow: 0 12px 30px rgba(0,0,0,.5); animation: kb-modal .2s ease-out; }
  #ef-toast span { color: #6b7a93; }
  @media (prefers-reduced-motion: reduce) { .card.ef-gone, #ef-toast, #efa, #efa .box { animation: none; } .card.ef-gone { opacity: 0; } }
  `;
  const style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  // ---- tiny DOM helpers ----
  const h = (tag, props = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k in el && k !== "list") el[k] = v;
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  };
  const card = (id) => document.querySelector(`#kb .card[data-id="${id}"]`);
  const archived = new Set();
  let toastTimer;
  function toast(text, sub, sticky) {
    document.getElementById("ef-toast")?.remove();
    document.body.append(h("div", { id: "ef-toast", role: "status" }, text, sub ? h("span", {}, "  ·  " + sub) : null));
    clearTimeout(toastTimer);
    if (!sticky) toastTimer = setTimeout(() => document.getElementById("ef-toast")?.remove(), 4200);
  }

  // ---- the simulated board writer ----
  const RESOLUTION = ["agent-resolvable", "needs-human"];
  function writerUpdate(before, after) {
    return new Promise((resolve) => setTimeout(() => {
      if (!RESOLUTION.some((l) => after.labels.includes(l))) {
        return resolve({ ok: false, field: "labels", reason: `refusing to update ${after.id}: it carries neither \`agent-resolvable\` nor \`needs-human\`. Keep one resolution label.`, skill: "starting-tasks" });
      }
      for (const d of after.dependencies) {
        if (d === after.id) return resolve({ ok: false, field: "deps", reason: `refusing to update ${after.id}: a task cannot depend on itself.` });
        const r = record(d);
        if (r && r.dependencies.includes(after.id)) return resolve({ ok: false, field: "deps", reason: `refusing to update ${after.id}: ${d} already depends on ${after.id}, so this dependency makes a cycle.` });
      }
      resolve({ ok: true });
    }, 650));
  }
  function writerArchive(id, refuse) {
    return new Promise((resolve) => setTimeout(() => resolve(refuse
      ? { ok: false, reason: `backlog task archive ${id} timed out after 30 s; the task was not archived.` }
      : { ok: true }), 600));
  }

  // ---- the task view: one layout and one set of controls for reading and editing; Edit only lets them take input ----
  const views = new WeakMap();
  const OWN_ROWS = ["profile", "labels", "milestone", "depends on"];
  const reactSnap = (modal) => [":scope > .k", ":scope > table", ":scope > .moves", ":scope > .refusal", ":scope > .mfoot"].map((s) => modal.querySelector(s)?.outerHTML || "").join("|");
  const laneName = (state) => document.querySelector(`#kb section[data-lane="${state}"] h2`)?.childNodes[1]?.textContent || state;
  const grow = (t) => { if (t.classList.contains("long")) return; t.style.height = "auto"; t.style.height = `${t.scrollHeight + 2}px`; };

  function mount(modal) {
    const id = modal.getAttribute("aria-label");
    const base = record(id);
    if (!base) return null;
    const acts = h("div", { class: "acts" });
    const head = h("div", { class: "tvhead" });
    const body = h("div", { class: "tvbody" });
    const foot = h("div", { class: "tvfoot" });
    const root = h("div", { class: "tv" }, head, body, foot);
    modal.classList.add("tvmode");
    modal.append(root);
    let mode = "read", draft = null, evidence = {}, refusal = null, saving = false, discarding = false, tried = false, saved = null, snap = "";

    const diff = () => {
      if (!draft) return [];
      const f = [];
      for (const k of ["title", "assignee", "priority", "milestone", "description", "plan", "notes"]) if (draft[k] !== base[k]) f.push(k);
      for (const [k, n] of [["labels", "labels"], ["dependencies", "deps"], ["ac", "ac"], ["dod", "dod"]]) if (JSON.stringify(draft[k]) !== JSON.stringify(base[k])) f.push(n);
      return f;
    };
    const missing = () => draft.ac.map((a, i) => (a.checked && !base.ac[i]?.checked && !(evidence[i] || "").trim() ? i : -1)).filter((i) => i >= 0);

    function onKey(e) {
      if (!root.isConnected) return document.removeEventListener("keydown", onKey, true);
      if (mode !== "edit" || document.getElementById("efa")) return;
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); discarding ? keep() : cancel(); }
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); save(); }
    }
    // The close button and the scrim would drop unsaved edits; with changes they ask first.
    function onClick(e) {
      if (!root.isConnected) return document.removeEventListener("click", onClick, true);
      if (mode !== "edit" || !diff().length || e.target.closest("#efa")) return;
      const closing = (modal.contains(e.target) && e.target.closest(".x")) || (e.target.closest("#kbm") && !modal.contains(e.target));
      if (closing) { e.stopPropagation(); e.preventDefault(); askDiscard(); }
    }
    document.addEventListener("click", onClick, true);

    function edit() {
      if (mode === "edit") return;
      draft = clone(base); evidence = {}; refusal = null; tried = false; discarding = false; saved = null; mode = "edit";
      render();
      head.querySelector(".fv.title")?.focus();
      document.addEventListener("keydown", onKey, true);
    }
    function leave() {
      mode = "read"; draft = null; refusal = null; discarding = false;
      document.removeEventListener("keydown", onKey, true);
      render();
    }
    function askDiscard() { discarding = true; renderActs(); acts.querySelector(".keep")?.focus(); }
    function keep() { discarding = false; renderActs(); }
    function cancel() { diff().length ? askDiscard() : leave(); }
    async function save() {
      if (saving || mode !== "edit" || !diff().length) return;
      if (missing().length) { tried = true; render(); body.querySelector(".ev.bad textarea")?.focus(); return; }
      saving = true; refusal = null; renderActs();
      const res = await writerUpdate(base, draft);
      saving = false;
      if (!root.isConnected) return;
      if (!res.ok) { refusal = res; render(); body.scrollTop = 0; return; }
      const changed = diff();
      Object.assign(base, clone(draft));
      saved = `Saved ${changed.length} field${changed.length > 1 ? "s" : ""} (${changed.join(", ")}) · one board-writer update`;
      const t = card(id)?.querySelector(".t");
      if (t) t.textContent = base.title;
      leave();
      body.scrollTop = 0;
    }

    function render() {
      const top = body.scrollTop;
      const editing = mode === "edit";
      const src = editing ? draft : base;
      root.classList.toggle("editing", editing);
      // Read mode keeps every control in place and only refuses input.
      const lock = (el) => { if (!editing) { el.tabIndex = -1; if ("readOnly" in el) el.readOnly = true; } return el; };
      const set = (key) => (e) => { src[key] = e.target.value; refreshDirty(); };
      const select = (key, options, label) => lock(h("select", { class: "fv", "aria-label": label, onchange: set(key) },
        options.map(([v, t]) => h("option", { value: v, selected: v === src[key] }, t))));
      const txt = (key, label, long) => lock(h("textarea", { class: long ? "fv long" : "fv", rows: long ? 7 : 1, value: src[key], placeholder: "—", "aria-label": label, oninput: (e) => { set(key)(e); grow(e.target); } }));
      function chips(key, all, placeholder, kindOf) {
        const box = h("div", { class: "fv chips" });
        const sugg = h("div", { class: "sugg", hidden: true });
        const input = lock(h("input", { type: "text", class: "ci", placeholder, "aria-label": placeholder }));
        const empty = h("span", { class: "none" }, "—");
        let pick = 0;
        const draw = () => {
          box.querySelectorAll(".chip").forEach((c) => c.remove());
          empty.hidden = !!src[key].length;
          src[key].forEach((v) => box.insertBefore(h("span", { class: `chip${kindOf?.(v) ? " " + kindOf(v) : ""}${base[key].includes(v) ? "" : " new"}`, title: key === "dependencies" ? agents().find((a) => a.id === v)?.title || null : null }, v,
            h("button", { "aria-label": `Remove ${v}`, tabIndex: editing ? 0 : -1, onclick: (e) => { e.preventDefault(); src[key] = src[key].filter((x) => x !== v); draw(); refreshDirty(); } }, "×")), empty));
        };
        const options = () => {
          const q = input.value.trim().toLowerCase();
          return all().filter(([v]) => !src[key].includes(v) && (!q || v.toLowerCase().includes(q))).slice(0, 7);
        };
        const showSugg = () => {
          const opts = options();
          sugg.hidden = !opts.length || document.activeElement !== input;
          pick = Math.min(pick, Math.max(0, opts.length - 1));
          sugg.replaceChildren(...opts.map(([v, note], i) => h("div", { class: i === pick ? "on" : "", onmousedown: (e) => { e.preventDefault(); add(v); } }, v, note ? h("span", {}, note) : null)));
        };
        const add = (v) => { if (v && !src[key].includes(v)) { src[key] = [...src[key], v]; input.value = ""; draw(); refreshDirty(); showSugg(); } };
        input.addEventListener("input", () => { pick = 0; showSugg(); });
        input.addEventListener("focus", showSugg);
        input.addEventListener("blur", () => (sugg.hidden = true));
        input.addEventListener("keydown", (e) => {
          const opts = options();
          if (e.key === "ArrowDown") { e.preventDefault(); pick = Math.min(pick + 1, opts.length - 1); showSugg(); }
          else if (e.key === "ArrowUp") { e.preventDefault(); pick = Math.max(pick - 1, 0); showSugg(); }
          else if (e.key === "Enter" && !(e.metaKey || e.ctrlKey)) { e.preventDefault(); add(opts[pick]?.[0] || input.value.trim()); }
          else if (e.key === "Backspace" && !input.value && src[key].length) { src[key] = src[key].slice(0, -1); draw(); refreshDirty(); }
        });
        box.append(empty, input, sugg);
        draw();
        return box;
      }
      const sec = (key, name, extra, ...content) => h("section", { class: "sec", "data-key": key }, h("div", { class: "sh" }, h("span", { class: "t" }, name), extra), ...content);
      function checks(key, name, withEvidence) {
        const n = h("span", { class: "n" });
        const list = h("div", { class: "list" });
        const paint = () => {
          n.textContent = `${src[key].filter((x) => x.checked).length}/${src[key].length}`;
          list.replaceChildren(...src[key].flatMap((it, i) => {
            const rowEl = h("div", { class: `item${it.checked ? " done" : ""}` },
              lock(h("input", { type: "checkbox", checked: it.checked, "aria-label": `${name} #${i + 1} done`, onclick: (e) => { if (!editing) e.preventDefault(); }, onchange: (e) => { it.checked = e.target.checked; paint(); refreshDirty(); } })),
              lock(h("input", { type: "text", class: "fv", value: it.text, "aria-label": `${name} #${i + 1}`, oninput: (e) => { it.text = e.target.value; refreshDirty(); } })),
              h("button", { class: "rm", tabIndex: editing ? 0 : -1, "aria-label": `Remove ${name} #${i + 1}`, title: "Remove", onclick: (e) => { e.preventDefault(); src[key].splice(i, 1); paint(); refreshDirty(); } }, "×"));
            if (!(editing && withEvidence && it.checked && !base[key][i]?.checked)) return [rowEl];
            const bad = tried && !(evidence[i] || "").trim();
            return [rowEl, h("div", { class: "item" }, h("span"), h("div", { class: `ev${bad ? " bad" : ""}` },
              h("span", { class: "h" }, bad ? `#${i + 1} needs its evidence before Save` : `Evidence for #${i + 1}: the command and its result (recorded with checkpoint-ac)`),
              h("textarea", { rows: 2, value: evidence[i] || "", placeholder: "uv run pytest lib/... -k ... : 4 passed", "aria-label": `Evidence for #${i + 1}`, oninput: (e) => { evidence[i] = e.target.value; } })))];
          }));
        };
        paint();
        const add = h("button", { class: "add", tabIndex: editing ? 0 : -1, onclick: (e) => { e.preventDefault(); src[key].push({ text: "", checked: false }); paint(); refreshDirty(); list.querySelector(".item:last-child .fv")?.focus(); } }, `+ Add ${withEvidence ? "criterion" : "item"}`);
        return sec(key, name, [n, add], list);
      }

      const profiles = [["", "unassigned"], ...PROFILES.map((p) => [p, p])];
      if (base.assignee && !PROFILES.includes(base.assignee)) profiles.push([base.assignee, base.assignee]);
      const nh = (v) => (v === "needs-human" ? "nh" : "");
      const row = (key, name, control) => h("tr", { "data-key": key }, h("td", {}, name), h("td", {}, control));
      const reactRows = [...modal.querySelectorAll(":scope > table tr")].filter((tr) => tr.cells.length > 1 && !OWN_ROWS.includes(tr.cells[0].textContent.trim()));
      const rmoves = [...modal.querySelectorAll(":scope > .moves button")];
      const rrefusal = modal.querySelector(":scope > .refusal");
      const link = modal.querySelector(":scope > .mfoot a")?.cloneNode(true);
      if (link) link.addEventListener("click", (e) => { if (mode === "edit" && diff().length) { e.preventDefault(); askDiscard(); } });

      head.replaceChildren(
        h("div", { class: "ttl" },
          lock(h("textarea", { class: "fv title", rows: 1, value: src.title, "aria-label": "Title", "data-key": "title",
            onkeydown: (e) => { if (e.key === "Enter" && !(e.metaKey || e.ctrlKey)) e.preventDefault(); },
            oninput: (e) => { e.target.value = e.target.value.replace(/\n/g, " "); set("title")(e); grow(e.target); } })),
          h("div", { class: "k" }, modal.querySelector(":scope > .k")?.textContent || `${id} · ${laneName(base.state)}`, link ? [" · ", link] : null)),
        acts);
      body.replaceChildren(...[
        editing && refusal ? h("div", { class: "refused", role: "alert" }, h("b", {}, "Not saved: "), refusal.reason,
          h("div", { class: "k2" }, `Nothing was written. Fix the field and Save again${refusal.skill ? ` · see ${refusal.skill}` : ""}.`)) : null,
        !editing && saved ? h("div", { class: "saved", role: "status" }, saved) : null,
        h("table", {}, h("tbody", {},
          row("assignee", "profile", select("assignee", profiles, "Profile")),
          row("priority", "priority", select("priority", PRIORITIES.map((p) => [p, p]), "Priority")),
          row("labels", "labels", chips("labels", () => allLabels().map((l) => [l, `${agents().filter((a) => a.labels.includes(l)).length}`]), "add a label…", nh)),
          row("milestone", "milestone", select("milestone", [["", "—"], ...milestones().map((m) => [m, m])], "Milestone")),
          row("deps", "depends on", chips("dependencies", () => agents().filter((a) => a.id !== id).map((a) => [a.id, a.title.length > 34 ? a.title.slice(0, 33) + "…" : a.title]), "add a task…")),
          reactRows.map((tr) => h("tr", { class: "ro" }, h("td", {}, tr.cells[0].textContent), h("td", { innerHTML: tr.cells[1].innerHTML }))))),
        !editing && rrefusal ? rrefusal.cloneNode(true) : null,
        sec("description", "Description", null, txt("description", "Description")),
        checks("ac", "Acceptance criteria", true),
        checks("dod", "Definition of done", false),
        sec("plan", "Implementation plan", null, txt("plan", "Implementation plan", true)),
        sec("notes", "Notes", null, txt("notes", "Notes", true)),
      ].filter(Boolean));
      if (editing && refusal) root.querySelectorAll(`[data-key="${refusal.field}"]`).forEach((el) => el.classList.add("bad"));
      root.querySelectorAll("textarea.fv").forEach(grow);
      body.scrollTop = top;
      const lanes = rmoves.filter((b) => !b.classList.contains("start")), start = rmoves.find((b) => b.classList.contains("start"));
      const proxy = (b) => () => modal.querySelectorAll(":scope > .moves button")[rmoves.indexOf(b)]?.click();
      foot.replaceChildren(...[
        lanes.length ? moveMenu(lanes, proxy) : null,
        start ? h("button", { class: "startbtn", disabled: editing || start.disabled, title: editing ? "Save or cancel the edit first" : start.title || null, onclick: proxy(start) }, start.textContent) : null,
      ].filter(Boolean));
      renderActs();
    }
    // Move to: one menu button whose items drive React's lane moves; Start session sits to its right. Both are disabled while editing.
    function moveMenu(rmoves, proxy) {
      const items = rmoves.map((b, i) => {
        const m = b.textContent.trim().match(/^(\S)\s+(.*)$/) || [null, "→", b.textContent.trim()];
        return h("div", { role: "menuitem", "aria-disabled": b.disabled ? "true" : "false", title: b.title || null,
          onmousemove: () => focusItem(i), onclick: (e) => { e.stopPropagation(); pick(i); } }, h("span", { class: "g" }, m[1]), m[2]);
      });
      const menu = h("div", { class: "mvmenu", role: "menu", hidden: true }, items);
      const btn = h("button", { class: "mvbtn", "aria-haspopup": "menu", "aria-expanded": "false", disabled: mode === "edit",
        title: mode === "edit" ? "Save or cancel the edit first" : null, onclick: (e) => { e.stopPropagation(); menu.hidden ? open(0) : close(); } }, "Move to");
      let on = -1;
      const focusItem = (i) => { on = i; items.forEach((el, j) => el.classList.toggle("on", j === i)); };
      const open = (i) => { menu.hidden = false; btn.setAttribute("aria-expanded", "true"); focusItem(i); document.addEventListener("click", close, { once: true }); };
      function close() { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); focusItem(-1); }
      function pick(i) { if (rmoves[i].disabled) return; close(); proxy(rmoves[i])(); }
      const wrap = h("div", { class: "mv", onkeydown: (e) => {
        if (menu.hidden) { if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); open(e.key === "ArrowUp" ? items.length - 1 : 0); } return; }
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); btn.focus(); }
        else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); focusItem((on + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length); }
        else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(on); }
        else if (e.key === "Tab") close();
      } }, menu, btn);
      return wrap;
    }
    // The actions sit in the header's right corner: Hide task, Archive, Edit; Cancel and Save take their place while editing.
    function renderActs() {
      if (mode === "read") {
        const hide = modal.querySelector(":scope > .mfoot .hidebtn");
        acts.replaceChildren(...[
          hide ? h("button", { class: hide.className, onclick: () => hide.click() }, hide.textContent) : null,
          h("button", { class: "archbtn", onclick: () => askArchive(id) }, "Archive…"),
          h("button", { class: "editbtn", onclick: edit }, "✎ Edit")].filter(Boolean));
      } else if (discarding) {
        const n = diff().length;
        acts.replaceChildren(
          h("span", { class: "cnt disc", role: "alert" }, `Discard ${n} change${n > 1 ? "s" : ""}?`),
          h("button", { class: "hidebtn keep", onclick: keep }, "Keep editing"),
          h("button", { class: "dangerbtn", onclick: leave }, "Discard"));
      } else {
        acts.replaceChildren(
          h("span", { class: "cnt" }),
          h("button", { class: "hidebtn", title: "Esc", onclick: cancel }, "Cancel"),
          h("button", { class: "savebtn", title: "Ctrl+Enter", onclick: save }, saving ? [h("span", { class: "spin" }), "Saving…"] : "Save"));
      }
      refreshDirty();
    }
    function refreshDirty() {
      const d = diff();
      root.querySelectorAll("[data-key]").forEach((el) => el.classList.toggle("dirty", d.includes(el.dataset.key)));
      const cnt = acts.querySelector(".cnt:not(.disc)");
      if (cnt) { cnt.textContent = d.length ? `${d.length} field${d.length > 1 ? "s" : ""} changed` : "No changes"; cnt.classList.toggle("on", !!d.length); }
      const sv = acts.querySelector(".savebtn");
      if (sv) sv.disabled = !d.length || saving;
    }

    const v = {
      id, edit, save, render,
      get draft() { return draft; },
      markTried() { tried = true; render(); },
      sync() { if (mode !== "read") return; const s = reactSnap(modal); if (s !== snap) { snap = s; render(); } },
      destroy() { root.remove(); modal.classList.remove("tvmode"); views.delete(modal); document.removeEventListener("keydown", onKey, true); document.removeEventListener("click", onClick, true); },
    };
    views.set(modal, v);
    return v;
  }

  // ---- archive: a confirm with a reason, from every column ----
  function askArchive(id, opts = {}) {
    const r = record(id);
    if (!r) return;
    const a = agents().find((x) => x.id === id);
    const pr = r.pr && !r.pr.merged ? r.pr : null;
    const session = a && (a.state === "in_progress" || opts.session) ? { machine: "in-progress", state: "implementing", ago: "3m" } : null;
    const lane = document.querySelector(`#kb section[data-lane="${r.state}"] h2`)?.childNodes[1]?.textContent || r.state;
    let refused = null;
    let busy = false;
    const reason = h("textarea", { placeholder: "e.g. superseded by the m-80 cohort; test task created by a leaked fixture", "aria-label": "Reason" });
    const scrim = h("div", { id: "efa", onclick: (e) => e.target === scrim && close() });
    const close = () => { scrim.remove(); document.removeEventListener("keydown", onKey, true); };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); if (!busy) close(); }
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); go(); }
    };
    async function go() {
      if (busy) return;
      busy = true; refused = null; paint();
      const c = card(id);
      c?.classList.add("ef-arch");
      const res = await writerArchive(id, opts.refuse && !opts.done);
      busy = false;
      if (!res.ok) {
        opts.done = true;
        refused = res.reason;
        c?.classList.remove("ef-arch");
        paint();
        return;
      }
      close();
      document.querySelector("#kbm .modal .x")?.click();
      archived.add(id);
      if (c) {
        c.classList.add("ef-gone");
        setTimeout(() => { c.style.display = "none"; fixCounts(); }, 450);
      }
      const why = reason.value.trim();
      toast(`${id} archived`, why ? "reason saved as a task comment" : "no reason given", opts.sticky);
    }
    const box = h("div", { class: "box", role: "alertdialog", "aria-label": `Archive ${id}` });
    function paint() {
      box.replaceChildren(...[
        h("h3", {}, `Archive ${id}?`),
        h("div", { class: "k" }, `${r.title} · ${lane}`),
        h("div", {}, "It leaves the board for the archive. Its file, comments and history are kept; nothing else about the task changes."),
        pr ? h("div", { class: "warn" }, "⚠", h("span", {}, "Pull request ", h("a", { href: pr.url, target: "_blank", rel: "noopener" }, `#${pr.number}`), ` is open (checks ${pr.checks}). Archiving does not close it.`,
          h("span", { class: "k3" }, "Close or merge it on GitHub if it should not land."))) : null,
        session ? h("div", { class: "warn" }, "⚠", h("span", {}, `An agent session is working this task (${session.machine} · ${session.state}, ${session.ago} ago). Archiving does not stop it.`,
          h("span", { class: "k3" }, "The session's next board write will be refused once the task is archived."))) : null,
        h("label", {}, h("span", {}, "Reason ", h("i", {}, "· optional, saved as a task comment")), reason),
        refused ? h("div", { class: "refused", role: "alert" }, `Not archived: ${refused}`) : null,
        h("div", { class: "row" },
          h("span", { class: "hint" }, "Esc cancels"),
          h("span", { class: "sp" }),
          h("button", { onclick: close, disabled: busy }, "Cancel"),
          h("button", { class: "danger", disabled: busy, onclick: go }, busy ? "Archiving…" : refused ? "Try again" : `Archive ${id}`)),
      ].filter(Boolean));
    }
    paint();
    scrim.append(box);
    document.body.append(scrim);
    document.addEventListener("keydown", onKey, true);
    reason.focus();
    return { go };
  }
  // React redraws the counts on every tick; its number stays in the DOM and the reduced one is drawn over it in ::after.
  function reduceCount(el, scope) {
    if (!el || !/^\d+$/.test(el.textContent)) return;
    const gone = [...archived].filter((id) => scope.querySelector(`.card[data-id="${id}"]`)).length;
    const shown = String(+el.textContent - gone);
    if (!gone) { delete el.dataset.efShown; return; }
    if (el.dataset.efShown === shown) return;
    if (!el.style.getPropertyValue("--ef-fs")) el.style.setProperty("--ef-fs", getComputedStyle(el).fontSize);
    el.dataset.efShown = shown;
  }
  function fixCounts() {
    for (const col of document.querySelectorAll("#kb section[data-lane]")) {
      reduceCount(col.querySelector("h2 .c"), col);
      for (const b of col.querySelectorAll(".bucket")) reduceCount(b.querySelector(".bh .c"), b);
    }
  }

  // ---- watch the page: give each task modal its view, keep archived cards gone across React re-renders ----
  const obs = new MutationObserver(() => {
    for (const m of document.querySelectorAll("#kbm .modal:not(.ask)")) {
      const v = views.get(m);
      if (v && v.id !== m.getAttribute("aria-label")) v.destroy();
      (views.get(m) || mount(m))?.sync();
    }
    for (const id of archived) { const c = card(id); if (c && !c.classList.contains("ef-gone")) { c.classList.add("ef-gone"); c.style.display = "none"; } }
    if (archived.size) fixCounts();
    for (const [id, r] of records) { const t = card(id)?.querySelector(".t"); if (t && t.textContent !== r.title) t.textContent = r.title; }
  });
  const boot = () => {
    obs.observe(document.body, { childList: true, subtree: true });
    if (!preset || !preset.open) return;
    const pickTask = () => {
      const as = agents();
      if (preset.open === "pr") return as.find((a) => a.state === "in_progress" && (fixture().pulls || {})[a.id]);
      return as.find((a) => a.state === preset.open && a.labels.includes("agent-resolvable")) || as.find((a) => a.state === preset.open);
    };
    const t = pickTask();
    if (!t) return;
    let tries = 0;
    const iv = setInterval(() => {
      const c = card(t.id);
      if (!c && ++tries < 80) return;
      clearInterval(iv);
      if (!c) return;
      c.scrollIntoView({ block: "center" });
      c.click();
      setTimeout(() => {
        const m = document.querySelector("#kbm .modal:not(.ask)");
        const v = m && (views.get(m) || mount(m));
        if (!v) return;
        v.sync();
        if (preset.edit) {
          v.edit();
          if (preset.evidence) { v.draft.ac[0].checked = true; v.markTried(); }
          if (preset.refuse) {
            v.draft.labels = v.draft.labels.filter((l) => !RESOLUTION.includes(l));
            v.draft.priority = v.draft.priority === "High" ? "Medium" : "High";
            v.render();
            v.save();
          }
        }
        if (preset.archive) {
          const ar = askArchive(t.id, { refuse: preset.archiveRefuse, session: preset.open === "pr", sticky: preset.confirm });
          if (preset.archiveRefuse || preset.confirm) ar.go();
        }
      }, 250);
    }, 100);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
