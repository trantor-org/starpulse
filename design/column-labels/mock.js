// Design mockup layer (per-viewer column labels and state-role display), never part of the page. The page above is the branch's real page,
// built with column-labels-src.patch, over the PR demo's capture. This layer plays serve's GET/PUT /api/views/columns for the install's one
// viewer: each starting state (?s=default|relabeled|hidden|reordered|one|refusal|offline), its refusals (a label another column already
// uses, one over 40 characters, every column hidden), a save serve never answers (?s=offline), the view (?view=kanban|constellation) and
// the text size (?fs=100|125|150). ?bar=0 hides this bar. What a viewer saves lasts for the tab, as serve would keep it for the install.
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
  const machineName = Object.fromEntries(states.map((x) => [x.id, x.name]));
  const SEEDS = {
    default: { columns: [], order: [] },
    relabeled: { columns: [
      { id: "ready", label: "Up next", hidden: false }, { id: "in_progress", label: "Doing", hidden: false },
      { id: "needs_attention", label: "Blocked on me", hidden: false }, { id: "done", label: "Shipped", hidden: false }], order: [] },
    hidden: { columns: [{ id: "waiting", label: null, hidden: true }, { id: "done", label: null, hidden: true }], order: [] },
    reordered: { columns: [], order: ["ready", "in_progress", "needs_attention", "review", "waiting", "done"] },
    one: { columns: states.filter((x) => x.id !== "in_progress").map((x) => ({ id: x.id, label: null, hidden: true })), order: [] },
  };
  SEEDS.refusal = SEEDS.relabeled;
  SEEDS.offline = SEEDS.relabeled;
  const key = `mock.columns.${s}`;
  let stored;
  try { stored = JSON.parse(sessionStorage.getItem(key) || "null"); } catch { stored = null; }
  stored = stored || SEEDS[s] || SEEDS.default;
  let down = false;
  let say = () => {};

  const reply = (status, body) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  // What serve refuses: the reason the page shows, and the state it names.
  function refusal(next) {
    const names = (v) => Object.fromEntries(states.map((x) => [x.id, (v.columns.find((c) => c.id === x.id)?.label || x.name).trim()]));
    const now = names(next);
    const was = (id) => stored.columns.find((c) => c.id === id)?.label ?? null;
    // the row this save changed is the one refused, so check changed labels first
    for (const c of [...next.columns].sort((a, b) => (a.label === was(a.id)) - (b.label === was(b.id)))) {
      if (c.label && c.label.length > 40) return [422, { error: "A label is at most 40 characters.", id: c.id }];
      const clash = states.find((x) => x.id !== c.id && c.label && now[x.id].toLowerCase() === c.label.trim().toLowerCase());
      if (clash) return [409, { error: `“${c.label.trim()}” already names ${machineName[clash.id] === now[clash.id] ? "a column" : `${machineName[clash.id]} (shown as ${now[clash.id]})`}.`, id: c.id }];
    }
    if (states.length && states.every((x) => next.columns.find((c) => c.id === x.id)?.hidden)) return [422, { error: "The board keeps one column drawn." }];
    return null;
  }
  globalThis.__MOCK_FETCH__ = (url, init = {}) => new Promise((resolve, reject) => setTimeout(() => {
    if (!String(url).endsWith("/api/views/columns")) return reject(new TypeError(`mockup serves no ${url}`));
    if ((init.method || "GET") === "GET") return resolve(reply(200, stored));
    if (down) { say("serve did not answer the save · press Server returns, then retry in the menu"); return reject(new TypeError("Failed to fetch")); }
    const next = JSON.parse(init.body);
    const no = refusal(next);
    if (no) { say(`serve refused (${no[0]}): ${no[1].error} · the page draws the last saved labels again`); return resolve(reply(...no)); }
    stored = next;
    try { sessionStorage.setItem(key, JSON.stringify(stored)); } catch { /* storage off: the save lasts for this load */ }
    say(`saved: ${next.columns.length} column(s) changed${next.order.length ? ", own order" : ""}`);
    resolve(reply(200, stored));
  }, init.method === "PUT" ? 450 : 60));

  const steps = {
    default: "the machine's names, roles and order · open Columns in the board header to rename, hide or drag a column",
    relabeled: "four columns relabeled · open a card: its Move menu reads the labels · the Star Map view draws them too",
    hidden: "Waiting and Done hidden · the Columns chip counts 2 changed · Show in the menu brings one back",
    reordered: "own order: Needs attention moved before Review · drag the ⋮⋮ handle or focus it and press ↑/↓ · Machine order puts it back",
    one: "one column drawn · its Hide button is disabled: the board keeps one column",
    refusal: "type Doing into Review's field and pause or press Enter: serve refuses it, the row names why, and the label goes back",
    offline: "serve is down: rename a column, then Server returns, then retry in the menu's footer",
  };

  // The review bar: every state, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      width: max-content; max-width: min(900px, calc(100vw - 24px)); box-sizing: border-box; padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.92);
      font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    @media (max-width: 900px) { #mockbar { bottom: auto; top: 6px; max-width: calc(100vw - 16px); } }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; flex-wrap: wrap; gap: 3px; align-items: center; }
    #mockbar a, #mockbar button { all: unset; padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on, #mockbar button { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
    #mockbar button[hidden] { display: none; }
    #mockbar i { flex-basis: 100%; text-align: center; font-style: normal; color: #b6c0d3; }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), s, fs: q.get("fs") || "100" };
  const groups = [
    ["State", "s", [["default", "Machine"], ["relabeled", "Relabeled"], ["hidden", "Hidden"], ["reordered", "Reordered"], ["one", "One column"],
      ["refusal", "Refusal"], ["offline", "Serve down"]]],
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
      a.onclick = () => { try { sessionStorage.removeItem(`mock.columns.${k === "s" ? v : s}`); } catch { /* nothing kept */ } };
      g.append(a);
    }
    bar.append(g);
  }
  const back = document.createElement("button");
  back.textContent = "Server returns";
  back.hidden = s !== "offline";
  back.onclick = () => { down = false; back.hidden = true; say("serve is back · press retry in the menu's footer"); };
  const line = document.createElement("i");
  bar.append(back, line);
  say = (t) => (line.textContent = t);
  down = s === "offline";
  say(steps[s] || steps.default);

  // Once the Kanban has drawn, show the bar; the refusal and serve-down states open the Columns menu.
  const start = (tries = 150) => {
    const chip = [...document.querySelectorAll("#kb .fchip")].find((c) => /^Columns/.test(c.textContent));
    if (chip || (q.get("view") !== "kanban" && document.querySelector("canvas"))) {
      if (q.get("bar") !== "0") document.body.append(bar);
      if (chip && (s === "refusal" || s === "offline" || q.get("open") === "1")) chip.click();
    } else if (tries) setTimeout(() => start(tries - 1), 100);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => start());
  else start();
})();
