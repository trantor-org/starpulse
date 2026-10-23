// Design mockup layer (per-viewer column labels and state-role display), never part of the page. The page above is the branch's real page,
// built with column-labels-src.patch, over the PR demo's capture. This layer plays serve's GET /api/views/columns for the install's one
// viewer, as `starpulse columns` left it: each starting state (?s=default|relabeled|hidden|one), the view (?view=kanban|constellation) and
// the text size (?fs=100|125|150). ?bar=0 hides this bar. The page only reads the columns: labels and hidden columns are set with the CLI,
// and the columns keep the machine's order.
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("view")) { q.set("view", "kanban"); history.replaceState(null, "", `?${q}`); }
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  const s = q.get("s") || "default";
  const board = (window.__FLOW_FIXTURE__?.flows || []).find((f) => f.name === "board");
  const states = board?.machine?.states || [];
  const LABELS = [["ready", "Up next"], ["in_progress", "Doing"], ["needs_attention", "Blocked on me"], ["done", "Shipped"]];
  const HIDDEN = { hidden: ["waiting", "done"], one: states.map((x) => x.id).filter((id) => id !== "in_progress") };
  const SEEDS = {
    default: { columns: [] },
    relabeled: { columns: LABELS.map(([id, label]) => ({ id, label, hidden: false })) },
    hidden: { columns: HIDDEN.hidden.map((id) => ({ id, label: null, hidden: true })) },
    one: { columns: HIDDEN.one.map((id) => ({ id, label: null, hidden: true })) },
  };
  const stored = SEEDS[s] || SEEDS.default;

  const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  globalThis.__MOCK_FETCH__ = (url) => new Promise((resolve, reject) => setTimeout(() => {
    if (!String(url).endsWith("/api/views/columns")) return reject(new TypeError(`mockup serves no ${url}`));
    resolve(reply(200, stored));
  }, 60));

  // The CLI run that leaves serve holding each state, and what to look at.
  const cli = {
    default: ["starpulse columns reset"],
    relabeled: LABELS.map(([id, label]) => `starpulse columns label ${id} "${label}"`),
    hidden: [`starpulse columns hide ${HIDDEN.hidden.join(" ")}`],
    one: [`starpulse columns hide ${HIDDEN.one.join(" ")}`],
  };
  const steps = {
    default: "the machine's names and order · hover a header's mark for its role",
    relabeled: "hover a relabeled header for the machine's name · open a card: its Move menu reads the labels · the Star Map draws them too",
    hidden: "Waiting and Done are not drawn · the rest keep the machine's order",
    one: "one column drawn: the CLI refuses hiding the last one",
  };

  // The review bar: every state, each a link to its own address, and the CLI run behind it.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      width: max-content; max-width: min(900px, calc(100vw - 24px)); box-sizing: border-box; padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.92);
      font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    @media (max-width: 900px) { #mockbar { bottom: auto; top: 6px; max-width: calc(100vw - 16px); } }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; flex-wrap: wrap; gap: 3px; align-items: center; }
    #mockbar a { all: unset; cursor: pointer; padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
    #mockbar code { flex-basis: 100%; text-align: center; font: 10.5px ui-monospace, monospace; color: #fde68a; white-space: pre-wrap; overflow-wrap: anywhere; }
    #mockbar i { flex-basis: 100%; text-align: center; font-style: normal; color: #b6c0d3; }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), s, fs: q.get("fs") || "100" };
  const groups = [
    ["State", "s", [["default", "Machine"], ["relabeled", "Relabeled"], ["hidden", "Hidden"], ["one", "One column"]]],
    ["View", "view", [["kanban", "Kanban"], ["constellation", "Star Map"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, k, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      u.set(k, v);
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[k] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  const code = document.createElement("code");
  code.textContent = `$ ${(cli[s] || cli.default).join("\n$ ")}`;
  const line = document.createElement("i");
  line.textContent = steps[s] || steps.default;
  bar.append(code, line);

  // Once the page has drawn, show the bar.
  const start = (tries = 150) => {
    if (document.querySelector("#kb #cols section") || (q.get("view") !== "kanban" && document.querySelector("canvas"))) {
      if (q.get("bar") !== "0") document.body.append(bar);
    } else if (tries) setTimeout(() => start(tries - 1), 100);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => start());
  else start();
})();
