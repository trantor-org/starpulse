// Design mockup layer (the Kanban autopilot toggle and capacity strip), never part of the page. The page above is the branch's real page over the
// PR demo's capture, with autopilot-src.patch: the strip replaces Connect a tracker in the Kanban toolbar, which moves to an Admin card.
// This layer answers /api/autopilot with a simulated admission loop and adds the review bar. States (?s=):
//   on       admitting: the next pick starts (its card moves to In Progress), fills the last session, and the one after waits on Sessions until a session settles
//   off      paused: admission stopped, three sessions still running, the meters dimmed
//   over     on, RAM over its limit and CPU near it: the next pick waits on RAM
//   empty    on, nothing eligible
//   refused  on; turning it off is refused, as a write from outside loopback and RFC 1918 is
//   down     the server has no autopilot route: the strip says so
// ?view=admin shows Connect a tracker on the Admin view, and ?fs=100|125|150 sets the text size. It runs before the page's module.
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("view")) { q.set("view", "kanban"); history.replaceState(null, "", `?${q}`); }
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = Number(q.get("fs") || 100);
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  const STATES = ["on", "off", "over", "empty", "refused", "down"];
  const s = STATES.includes(q.get("s")) ? q.get("s") : "on";
  const F = window.__FLOW_FIXTURE__;
  const now = () => Date.now() / 1000;

  // the tasks the strip names come from the capture: Ready ones are picks, In Progress ones the sessions in flight
  const board = F?.flows?.find((f) => f.name === "board");
  const agents = board?.agents ?? [];
  const titleOf = (a) => a.title || a.label || a.name || a.id;
  const inLane = (lane) => agents.filter((a) => a.state === lane);
  const MODELS = ["opus · high", "sonnet · high", "sonnet · medium"];
  const session = (a, i) => ({ task: a.id, title: titleOf(a), model: MODELS[i % MODELS.length], started: now() - (14 + 23 * i) * 60,
    url: `https://claude.ai/code/session_demo${String(i + 1).padStart(3, "0")}` });
  const flying = inLane("in_progress").slice(0, 3).map(session);

  // the loop's state: limits are trantor's defaults in the spec's shape; CPU and RAM drift with the sampler
  const st = { on: s !== "off", cpu: 41, ram: 58, review: 13, sessions: flying.slice(0, s === "on" ? 2 : 3), phase: "starting", at: now() };
  if (s === "over") Object.assign(st, { cpu: 74, ram: 91 });
  const LIM = { cpu: 80, ram: 85, sessions: 4, review: 24 };
  const dim = (key, name, used, limit, unit, detail) => ({ key, name, used, limit, unit, detail });
  const jitter = (v, by, lo, hi) => Math.max(lo, Math.min(hi, Math.round(v + (Math.random() * 2 - 1) * by)));

  // the on state's cycle: the pick starts (4 s), takes the last session, the next waits on Sessions; a session settles (12 s) and frees it
  let srv = null; // the demo server, so an admitted task moves to In Progress and a settled one to Review on the board
  // the demo server's own move checks the Board machine's drag rules; an admission is a start, so the card is placed directly,
  // and held out of the demo's random walk as a card the viewer created is, so it stays where autopilot put it
  const place = (id, to) => {
    if (!srv) return;
    srv.created?.add(id);
    const next = structuredClone(srv.snapshot), card = next.flows.find((f) => f.name === "board")?.agents.find((x) => x.id === id);
    if (card) { Object.assign(card, { state: to, entered: now() }); srv.publish(next); }
  };
  // the pick: the first card drawn in Ready with no open dependency, so the strip names the card at the top of the column
  const pickNow = () => {
    const started = new Set(st.sessions.map((x) => x.task)); // the column redraws after the poll that admitted a card
    const card = [...document.querySelectorAll('#cols section[data-lane="ready"] .card[data-id]')].find((c) => !c.querySelector(".dep") && !started.has(c.dataset.id));
    if (!document.querySelector('#cols section[data-lane="ready"] .card')) { // the column has not drawn yet: the capture's first free Ready card
      const a = inLane("ready").filter((x) => !(x.dependencies ?? []).length && !started.has(x.id))
        .sort((x, y) => (y.entered ?? 0) - (x.entered ?? 0) || y.id.localeCompare(x.id, undefined, { numeric: true }))[0];
      return a && { task: a.id, title: titleOf(a) };
    }
    if (!card) return undefined;
    srv?.created?.add(card.dataset.id); // a named pick stays in Ready until autopilot starts it, as the real loop would hold it
    return { task: card.dataset.id, title: card.querySelector(".t")?.textContent ?? card.dataset.id };
  };
  function step() {
    if (s !== "on" || !st.on) return;
    const t = now() - st.at;
    const pick = pickNow();
    if (st.phase === "starting" && t > 4 && pick) {
      st.sessions = [...st.sessions, { ...session({ id: pick.task, title: pick.title }, st.sessions.length), started: now() }];
      place(pick.task, "in_progress");
      st.phase = st.sessions.length >= LIM.sessions ? "full" : "starting";
      st.at = now();
    } else if (st.phase === "full" && t > 12) {
      place(st.sessions[0].task, "review");
      st.sessions = st.sessions.slice(1);
      st.review = Math.min(LIM.review, st.review + 3);
      st.phase = "starting";
      st.at = now();
    }
  }

  function state() {
    step();
    st.cpu = jitter(st.cpu, 3, s === "over" ? 70 : 30, s === "over" ? 79 : 66);
    st.ram = jitter(st.ram, 1, s === "over" ? 89 : 52, s === "over" ? 93 : 64);
    const dims = [
      dim("cpu", "CPU", st.cpu, LIM.cpu, "%", `Host CPU over the last minute, ${st.cpu}% of 8 cores. Admission holds it under ${LIM.cpu}%.`),
      dim("ram", "RAM", st.ram, LIM.ram, "%", `Host memory in use, ${(st.ram * 0.32).toFixed(1)} of 32 GiB. Admission holds it under ${LIM.ram}%.`),
      dim("sessions", "Sessions", st.sessions.length, LIM.sessions, "", `Autopilot sessions running. Click for the list.`),
      dim("review", "Review", st.review, LIM.review, " pts", `Points waiting in Review: ${st.review}. Admission stops at ${LIM.review} so review keeps up.`),
    ];
    let next = null;
    const pick = pickNow();
    if (s !== "empty" && pick) {
      const over = dims.find((d) => d.used > d.limit);
      if (over) next = { ...pick, verdict: "waits", reason: `${over.name} ${over.used}/${over.limit}${over.unit.trim()}` };
      else if (st.sessions.length >= LIM.sessions) next = { ...pick, verdict: "waits", reason: `Sessions ${st.sessions.length}/${LIM.sessions}` };
      else if (s === "on") next = { ...pick, verdict: "starting", reason: "" };
      else next = { ...pick, verdict: "waits", reason: "Review would reach 26/24 pts" };
    }
    return { on: st.on, dimensions: dims, inFlight: st.sessions, next };
  }

  window.__MOCK_API__ = {
    "/api/autopilot": (init, server) => {
      srv = server;
      if (s === "down") return [{ error: "This server has no autopilot." }, 404];
      if (init?.method === "PUT") {
        if (s === "refused") return [{ error: "Autopilot changes are taken only from loopback or a private address; this request came from 203.0.113.24." }, 403];
        st.on = Boolean(JSON.parse(init.body || "{}").on);
        if (st.on) { st.phase = "starting"; st.at = now(); }
      }
      return [state(), 200];
    },
  };

  // The review bar: every variant, each a link to its own address.
  const bar = document.createElement("div");
  bar.id = "mockbar";
  bar.innerHTML = `<style>
    #mockbar { position: fixed; z-index: 50; bottom: 12px; left: 50%; transform: translateX(-50%); display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; justify-content: center;
      max-width: calc(100vw - 540px); padding: 6px 10px; border-radius: 9px; border: 1px dashed rgba(251,191,36,.45); background: rgba(10,12,20,.9); font: 11px Inter, system-ui, sans-serif; color: #6b7a93; }
    #mockbar b { color: #fbbf24; font-weight: 500; letter-spacing: .2em; font-size: 9.5px; }
    #mockbar span { display: inline-flex; gap: 3px; align-items: center; }
    #mockbar a { padding: 1px 6px; border-radius: 4px; border: 1px solid rgba(148,163,184,.18); color: #b6c0d3; text-decoration: none; }
    #mockbar a.on { border-color: #fbbf24; color: #fde68a; background: rgba(251,191,36,.10); }
  </style><b>MOCKUP</b>`;
  const cur = { view: q.get("view"), s, fs: q.get("fs") || "100" };
  const groups = [
    ["View", "view", [["kanban", "Kanban"], ["admin", "Admin"]]],
    ["Autopilot", "s", [["on", "On"], ["off", "Off"], ["over", "Over limit"], ["empty", "Nothing eligible"], ["refused", "Refused"], ["down", "Unavailable"]]],
    ["Text", "fs", [["100", "100%"], ["125", "125%"], ["150", "150%"]]],
  ];
  for (const [title, key, opts] of groups) {
    const g = document.createElement("span");
    g.append(title);
    for (const [v, l] of opts) {
      const a = document.createElement("a"), u = new URLSearchParams(location.search);
      u.set(key, v);
      if (key === "s") u.set("view", "kanban");
      a.href = `?${u}`;
      a.textContent = l;
      if (cur[key] === v) a.className = "on";
      g.append(a);
    }
    bar.append(g);
  }
  const mount = () => document.body.append(bar);
  if (document.body) mount(); else document.addEventListener("DOMContentLoaded", mount);
})();
