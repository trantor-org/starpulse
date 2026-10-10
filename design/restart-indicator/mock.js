// Design mockup layer (the restart-aware status indicator), never part of the page. The page above is the branch's real page, built with
// restart-indicator-src.patch, over the PR demo's capture. This layer plays what the server and the connection would do, on the real dot and
// its stats line: an announced restart (?s=restart), one that shipped a new page build (?s=update), an unannounced drop (?s=drop), each state
// held still (?s=wait|off|new), and the text size (?fs=100|125|150). Waits are shortened and named in the review bar.
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("view")) { q.set("view", "kanban"); history.replaceState(null, "", `?${q}`); }
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  const s = q.get("s") || "live";
  const IDLE_MS = 5000; // the page: 30 s
  const GRACE_MS = 8000; // the page: 20 s
  const OUTAGE_MS = 6000; // the live unit today: 2-13 s
  let say = () => {};
  const hud = () => window.__MOCK_HUD__;
  const asOf = () => (hud().get().stats.match(/\d{1,2}:\d{2}(?::\d{2})?(?: [AP]M)? MST/) || ["now"])[0];
  const set = (live, note) => hud().set({ live, note });
  const after = (ms, fn) => setTimeout(fn, ms);

  // No task view or menu open, nothing being typed, and no pointer or key input for IDLE_MS; a hidden tab is idle at once.
  let touched = Date.now();
  for (const ev of ["pointerdown", "pointermove", "keydown", "wheel"]) addEventListener(ev, () => (touched = Date.now()), { capture: true, passive: true });
  const busy = () => !!document.querySelector('[role="dialog"], dialog[open], [role="menu"]') || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
  const whenIdle = (fn) => {
    const t = setInterval(() => {
      const left = IDLE_MS - (Date.now() - touched);
      if (document.hidden || (!busy() && left <= 0)) { clearInterval(t); fn(); }
      else say(busy() ? "new build loaded · waiting: a task view, menu or field is open" : `new build loaded · reloads after ${Math.ceil(left / 1000)} s without input (page: 30 s)`);
    }, 250);
  };
  const reloaded = () => { const u = new URLSearchParams(location.search); u.set("s", "reloaded"); location.replace(`?${u}`); };

  const plays = {
    live: () => say("connected: the dot and line as they are today"),
    reloaded: () => say("the page reloaded itself onto the new build: live again"),
    wait: () => { set("wait", `restarting · ${asOf()}`); say("held: reconnecting (an announced restart)"); },
    off: () => { set("off", `offline · ${asOf()}`); say("held: lost"); },
    new: () => { set("on", "updating when idle"); say("held: a new build is loaded, waiting for idle"); },
    restart: () => { say("live · the server announces a restart in 2 s"); after(2000, () => {
      set("wait", `restarting · ${asOf()}`); say(`server announced a restart · board keeps its last state · back in ${OUTAGE_MS / 1000} s`);
      after(OUTAGE_MS, () => { set("on", ""); say("reconnected, same build: live"); }); }); },
    update: () => { say("live · the server announces a restart in 2 s"); after(2000, () => {
      set("wait", `restarting · ${asOf()}`); say(`server announced a restart · back in ${OUTAGE_MS / 1000} s with a new page build`);
      after(OUTAGE_MS, () => { set("on", "updating when idle"); whenIdle(reloaded); }); }); },
    drop: () => { say("live · the connection drops unannounced in 2 s"); after(2000, () => {
      set("wait", `retrying · ${asOf()}`); say(`connection lost with no announcement · retrying · lost after ${GRACE_MS / 1000} s (page: 20 s)`);
      after(GRACE_MS, () => { set("off", `offline · ${asOf()}`); say("no server for the grace period: lost · still retrying · press Server returns"); back.hidden = false; }); }); },
  };

  // The review bar: every state, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      max-width: calc(100vw - 540px); padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.9); font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; gap: 3px; align-items: center; }
    #mockbar a, #mockbar button { all: unset; padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on, #mockbar button { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
    #mockbar button[hidden] { display: none; }
    #mockbar i { flex-basis: 100%; text-align: center; font-style: normal; color: #b6c0d3; }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), s, fs: q.get("fs") || "100" };
  const groups = [
    ["Play", "s", [["live", "Live"], ["restart", "Restart"], ["update", "Restart + new build"], ["drop", "Unannounced drop"]]],
    ["Hold", "s", [["wait", "Reconnecting"], ["off", "Lost"], ["new", "New build"]]],
    ["View", "view", [["kanban", "Kanban"], ["dags", "DAGs"], ["constellation", "Star Map"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, key, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      u.set(key, v);
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[key] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  const back = document.createElement("button");
  back.textContent = "Server returns";
  back.hidden = true;
  back.onclick = () => { set("on", ""); back.hidden = true; say("reconnected: live"); };
  const line = document.createElement("i");
  bar.append(back, line);
  say = (t) => (line.textContent = t);

  // Once the page has drawn its first snapshot (the line reads "live · …"), play the state.
  const start = (tries = 150) => {
    if (hud() && /^live/.test(hud().get().stats)) { document.body.append(bar); (plays[s] || plays.live)(); }
    else if (tries) setTimeout(() => start(tries - 1), 100);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => start());
  else start();
})();
