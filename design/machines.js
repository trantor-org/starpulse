"use strict";
/*
  Design review only: the In Progress level as one sky, over the saved snapshot in data.js. It opens the way the live
  level does: from the Board, clicking the In progress galaxy zooms through into it, and right-click, Escape or
  Backspace at the fit zooms back out. The in-progress machine runs across the middle; every other lifecycle machine is a
  planet, a ring of its states with its tasks orbiting them. A machine entered from an in-progress state hangs below that
  state on a tether (declared by the state's flow:, or observed in the trails); a machine launched only by DAGs, or idle
  this hour, sits in the row above. A DAG is a star beside the machine it launches. Off unless the address names ?mv=.

  The sky always fits the screen and never scrolls. The wheel zooms about the cursor, drag pans once zoomed, and a planet
  unfolds into its whole machine, named states and all, as it grows. Flow lines are the page's own: a dashed gradient
  between the colours of the two states, streaming the way the flow runs. Hovering a task retraces its path in order,
  across every machine it has a session in, along those same lines; clicking it pins the trace and opens the panel.
  &level=in_progress opens in the sky, &fs=125 or &fs=150 sets the browser text size, &focus=<machine> opens flown into
  one machine, &pick=busy pins the task that sits on the most machines at once. running-skill-evals had no session in the
  saved snapshot, so two are seeded from the live shape (a task drafting a skill asks for a run).
*/
(() => {
  const P = new URLSearchParams(location.search);
  if (!P.get("mv")) return;
  if (P.get("fs")) document.documentElement.style.fontSize = `${+P.get("fs")}%`;
  // the page's own globals this layer reads and drives: its level stack, its transition, its night sky and go()
  const page = { get stack() { return stack; }, set trans(v) { trans = v; }, set mouse(v) { mouse = v; }, get stars() { return STARS; }, go: go };
  addEventListener("load", init);

  function init() {
    const S = window.SNAP, F = S.flows, TAU = Math.PI * 2, TZ = "America/Phoenix", IP = "in-progress", KMAX = 10;
    const ACT = "#fbbf24", DAGC = "#fcd34d", OFF = "#fb7185", PLANET = "#c084fc", INK = "#cfd9ea", SUB = "#94a3b8";
    const RAMP = ["#94a3b8", "#60a5fa", "#818cf8", "#a78bfa", "#c084fc", "#e879f9", "#f472b6", "#fbbf24", "#34d399"];
    const TIER = { deep: "#c4b5fd", standard: "#67e8f9", other: "#fde68a" };
    const tierOf = (m = "") => (/opus|deep/.test(m) ? "deep" : /sonnet|standard/.test(m) ? "standard" : "other");
    const rgba = (h, a) => { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
    const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const hhmm = (sec) => new Date(sec * 1000).toLocaleTimeString("en-US", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
    const easeO = (u) => 1 - Math.pow(1 - u, 3), ease = (u) => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, u) => a + (b - a) * u, smooth = (u) => { u = clamp(u, 0, 1); return u * u * (3 - 2 * u); };
    let FS = 1;
    const readFS = () => (FS = parseFloat(getComputedStyle(document.documentElement).fontSize) / 16 || 1);
    const NAVW = () => parseInt(getComputedStyle(document.documentElement).getPropertyValue("--nav")) || 52, RAILW = () => document.getElementById("rail").offsetWidth;

    // ---- page chrome: the live page's hover navigator and rail stay; in the sky this layer's canvas, clock, feed and legend stand in
    const css = document.createElement("style");
    css.textContent = `
      body.mv #c, body.mv #clock, body.mv #feed { display: none; }
      body:not(.mv) #mv, body:not(.mv) #mvtip, body:not(.mv) #mvclock, body:not(.mv) #mvzoom, body:not(.mv) #mvfeed { display: none; }
      #mv { position: fixed; left: 0; top: 0; display: block; cursor: default; } #mv.pan { cursor: grab; } #mv.drag { cursor: grabbing; } #mv.hot { cursor: pointer; }
      #mvtip { position: fixed; z-index: 4; pointer-events: none; padding: .5rem .7rem; border-radius: 8px; font-size: .75rem; line-height: 1.5; max-width: 26rem;
        background: rgba(12,19,34,.94); border: 1px solid rgba(148,163,184,.18); backdrop-filter: blur(6px); opacity: 0; transition: opacity .12s; color: #dbe4f3; }
      #mvtip .k { color: #6b7a93; font-size: .6875rem; } #mvtip b { font-weight: 500; }
      #mvclock { position: fixed; z-index: 4; top: 18px; right: calc(var(--rail) + 24px); font: .65625rem "JetBrains Mono", ui-monospace, monospace; color: #fbbf24; pointer-events: none; text-shadow: 0 0 6px #04060b, 0 0 12px #04060b; }
      #mvclock i { display: inline-block; width: 5px; height: 5px; border-radius: 50%; background: #fbbf24; margin-right: 6px; vertical-align: 1px; }
      body:has(#panel.open) #mvclock { opacity: 0; }
      #mvzoom, #mvrev { position: fixed; z-index: 4; bottom: 14px; display: flex; gap: 2px; align-items: center; font-size: .6875rem; color: #3f4c66; text-shadow: 0 0 6px #04060b, 0 0 12px #04060b; }
      #mvzoom { right: calc(var(--rail) + 18px); } #mvrev { left: calc(var(--nav) + 18px); }
      #mvzoom button, #mvrev button { all: unset; cursor: pointer; padding: .15rem .5rem; border-radius: 5px; color: #6b7a93; }
      #mvzoom button:hover, #mvrev button:hover { color: #dbe4f3; background: rgba(148,163,184,.08); } #mvrev button.on { color: #fbbf24; }
      #mvzoom .pct { min-width: 2.6rem; text-align: center; color: #6b7a93; font: .65625rem "JetBrains Mono", ui-monospace, monospace; }
      #mvfeed { font: 10.5px/1.75 "JetBrains Mono", ui-monospace, monospace; flex: 1; min-height: 0; overflow: hidden; }
      #mvfeed div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } #mvfeed b { font-weight: 400; color: #dbe4f3; } #mvfeed em { font-style: normal; opacity: .6; }
      #mvfeed div.new { animation: flash 1.2s; }
      #panel .mrow td:first-child i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
      /* the live navigator: a 250 px panel styled like the rail, always shown; every level is laid out between it and the rail */
      body.mvnav #nav { width: var(--nav); padding: 20px 18px; background: rgba(8,12,22,.78); backdrop-filter: blur(6px); border-right: 1px solid rgba(148,163,184,.10); overflow: hidden; }
      body.mvnav #nav::after, body.mvnav #full::before { display: none; }
      body.mvnav #full { position: static; width: auto; height: 100%; padding: 0; opacity: 1; pointer-events: auto; gap: 18px; }
      body.mvnav #crumbs { opacity: 1 !important; } body.mvnav #c { left: var(--nav); }
      #full .mvhead { position: relative; }
      #mvfold { all: unset; cursor: pointer; position: absolute; right: 0; top: -3px; width: 22px; height: 22px; box-sizing: border-box; border: 1px solid rgba(148,163,184,.22); border-radius: 6px; display: grid; place-items: center; color: #6b7a93; }
      #mvfold:hover { color: var(--ink); border-color: rgba(148,163,184,.4); }
      .mvviews .vw { all: unset; box-sizing: border-box; cursor: pointer; display: grid; grid-template-columns: 22px 1fr auto; align-items: center; gap: 6px; width: calc(100% + 16px); padding: 5px 8px; margin: 0 -8px; border-radius: 6px; color: var(--muted); font-size: 12px; }
      .mvviews .vw:hover { color: var(--ink); } .mvviews .vw.on { background: linear-gradient(90deg, rgba(167,139,250,.18), rgba(167,139,250,0)); color: var(--ink); box-shadow: inset 2px 0 0 #a78bfa; }
      .mvviews .vw b { font-weight: 400; font-size: 11px; color: var(--muted); } .mvviews svg { display: block; margin: auto; }
      #mvadmin { display: grid; grid-template-columns: 22px 1fr; gap: 6px; align-items: center; padding-top: 14px; margin: 0 -18px; padding-left: 18px; border-top: 1px solid rgba(148,163,184,.10); font-size: 12px; color: var(--muted); cursor: default; }
      /* folded ([ or the chevron): a 52 px strip that keeps only the Views icons, in the same place; no body moves */
      body.mvnav.navfold #nav { width: 52px; padding: 20px 8px; }
      body.mvnav.navfold #full > section:not(.mvhead):not(.mvviews), body.mvnav.navfold #mvadmin, body.mvnav.navfold .mvhead > :not(#mvfold),
        body.mvnav.navfold .mvviews h3, body.mvnav.navfold .vw > :not(svg) { display: none; }
      body.mvnav.navfold .mvhead { height: 22px; } body.mvnav.navfold #mvfold { right: auto; left: 7px; }
      body.mvnav.navfold .mvviews .vw { grid-template-columns: 1fr; width: 36px; height: 30px; margin: 0; padding: 0; }
    `;
    document.head.append(css);

    // ---- the live navigator, mocked over the page's own: views, search, layers (the current level's machines under its state), DAGs,
    // queues and Admin. It stays open at 250 px; the canvas of every level starts at its edge, so the page's Board is fitted there too
    const NAVL = 250, root = document.documentElement, navEl = document.getElementById("nav"), full = document.getElementById("full");
    root.style.setProperty("--nav", `${NAVL}px`); document.body.classList.add("mvnav");
    const svg = (d) => `<svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" stroke-width="1.2">${d}</svg>`;
    const head = full.firstElementChild; head.classList.add("mvhead"); head.querySelector("h1").textContent = "StarPulse";
    head.insertAdjacentHTML("beforeend", `<button id="mvfold" title="fold the navigator ([)">${svg('<path d="M8 3.5 5 6.5l3 3"/>')}</button>`);
    const boardN = () => document.querySelector("#layers .node .n")?.textContent || "";
    head.insertAdjacentHTML("afterend", `<section class="mvviews"><h3>Views</h3><button class="vw on">${svg('<circle cx="6.5" cy="6.5" r="4.5"/>')}<span>Star Map</span><b></b></button>`
      + `<a class="vw" href="?view=kanban">${svg('<path d="M3 3v7M6.5 3v5M10 3v3" stroke-width="2"/>')}<span>Kanban</span><b class="kn"></b></a></section>`);
    document.getElementById("q").placeholder = "search…";
    for (const h of full.querySelectorAll("h3")) if (h.textContent === "Constellations") h.textContent = "DAGs";
    full.insertAdjacentHTML("beforeend", `<div id="mvadmin" title="Admin is not part of this mockup">${svg('<circle cx="6.5" cy="6.5" r="2"/><path d="M6.5 1.5v2M6.5 9.5v2M1.5 6.5h2M9.5 6.5h2M3 3l1.4 1.4M8.6 8.6 10 10M3 10l1.4-1.4M8.6 4.4 10 3"/>')}<span>Admin</span></div>`);
    const setFold = (on) => { document.body.classList.toggle("navfold", on); document.querySelector("#mvfold svg").innerHTML = on ? '<path d="M5 3.5 8 6.5l-3 3"/>' : '<path d="M8 3.5 5 6.5l-3 3"/>'; try { localStorage.setItem("fv.nav.folded", on ? "1" : ""); } catch {} };
    document.getElementById("mvfold").addEventListener("click", () => setFold(!document.body.classList.contains("navfold")));
    addEventListener("keydown", (e) => { if (e.key === "[" && !/INPUT|TEXTAREA/.test(e.target.tagName)) setFold(!document.body.classList.contains("navfold")); });
    try { if (localStorage.getItem("fv.nav.folded")) setFold(true); } catch {}
    setInterval(() => { const k = navEl.querySelector(".kn"); if (k && k.textContent !== boardN()) k.textContent = boardN(); }, 1000);
    // the page sizes its canvas from innerWidth: run its resize with the panel's width taken off, its canvas moved to the panel's edge
    const iw = Object.getOwnPropertyDescriptor(window, "innerWidth"), pageResize = window.resize;
    window.resize = function () { const real = iw ? iw.get.call(window) : document.documentElement.clientWidth;
      Object.defineProperty(window, "innerWidth", { configurable: true, get: () => real - NAVL }); try { pageResize(); } finally { iw ? Object.defineProperty(window, "innerWidth", iw) : delete window.innerWidth; } };
    addEventListener("resize", () => window.resize()); window.resize();
    const cv = document.createElement("canvas"); cv.id = "mv"; document.body.prepend(cv);
    const mcx = cv.getContext("2d"), buf = document.createElement("canvas"), bcx = buf.getContext("2d");
    let cx = bcx; // the sky draws into an offscreen buffer; each frame lays it over the night sky, scaled while zooming through
    const el = (id, html = "") => { const d = Object.assign(document.createElement("div"), { id }); d.innerHTML = html; document.body.append(d); return d; };
    const tip = el("mvtip"), clockEl = el("mvclock");
    const zoomEl = el("mvzoom", `<button data-z="-1" title="zoom out (−)">−</button><span class="pct"></span><button data-z="1" title="zoom in (+)">+</button><button data-z="0" title="fit (0)">fit</button>`);
    const revEl = el("mvrev");
    const panel = document.getElementById("panel"), legendEl = document.getElementById("legend");
    const feed = Object.assign(document.createElement("div"), { id: "mvfeed" }); document.getElementById("feed").after(feed);
    const dash = (a, b, w = 1.2) => `<i style="background:linear-gradient(90deg,${a},${b});border-radius:0;height:${w}px;width:16px;vertical-align:3px"></i>`;
    const skyLegend = `<h3>Legend</h3>
      <span><i style="background:${TIER.deep}"></i>deep</span><span><i style="background:${TIER.standard}"></i>standard</span><span><i style="background:${TIER.other}"></i>other</span><br>
      <span>${dash(RAMP[2], PLANET)}declared tie</span> <span style="opacity:.75">${dash(RAMP[2], PLANET, 1)}observed tie</span><br>
      <span style="color:${DAGC}">✦</span> DAG <span style="margin-left:10px">${dash(RAMP[1], RAMP[5], 2.4)}task path</span><br>
      <span><i style="background:${ACT};box-shadow:0 0 6px ${ACT}"></i>activity now</span>`;
    let pageLegend = legendEl.innerHTML;

    // ---- the machines: in-progress and every other lifecycle machine, self-loops dropped (the tooltip names them)
    const M = {};
    for (const n of Object.keys(F)) if (n !== "board") {
      const f = F[n];
      M[n] = { name: n, states: f.machine.states, all: f.machine.transitions, trans: f.machine.transitions.filter((t) => t.source !== t.target),
        agents: f.agents.map((a) => ({ ...a, trail: [...(a.trail || [])], m: n })) };
    }
    const SUBS = Object.keys(M).filter((n) => n !== IP);
    const isFinal = (m, s) => !!M[m].states.find((x) => x.id === s)?.final;
    const stName = (m, s) => M[m].states.find((x) => x.id === s)?.name || s;
    const initOf = (m) => (M[m].states.find((s) => s.initial) || M[m].states[0]).id;
    const hasEdge = (m, a, b) => M[m].trans.some((t) => t.source === a && t.target === b);
    const boardTitle = Object.fromEntries((F.board?.agents || []).map((a) => [a.id, a.title]));
    const start = (a) => a.trail[0]?.at ?? a.active;
    const stateAt = (a, t) => { let s = null; for (const x of a.trail) if (x.at <= t) s = x.state; return s; };
    // seed running-skill-evals from the live shape: a task drafting or testing a skill asks for an eval run
    const seeded = new Set();
    if (M["running-skill-evals"] && !M["running-skill-evals"].agents.length && M["authoring-skills"]) {
      const src = M["authoring-skills"].agents.filter((a) => a.task && ["skill_tested", "skill_drafted"].includes(a.state)).slice(0, 2);
      src.forEach((a, i) => { const t0 = a.active + 60, tr = [{ state: "needed", event: "PREFLIGHT_BLOCKED", at: t0 }, { state: "ready", event: "PREFLIGHT_READY", at: t0 + 30 }, { state: "asked", event: "APPROVAL_ASKED", at: t0 + 60 }];
        if (i) tr.push({ state: "approved", event: "APPROVED", at: t0 + 90 }, { state: "running", event: "RUN_STARTED", at: t0 + 120 });
        M["running-skill-evals"].agents.push({ id: `seed-${i}`, title: a.title, model: a.model, kind: "interactive", badges: [], task: a.task, m: "running-skill-evals",
          state: tr.at(-1).state, steps: tr.length, trail: tr, active: tr.at(-1).at }); });
      if (src.length) seeded.add("running-skill-evals");
    }

    // ---- ties: declared (a state's flow:), observed (the state a task held when its session entered), DAG launches
    const TIES = [];
    const tieOf = (child, pm, ps, kind, dag) => TIES.find((t) => t.child === child && t.pm === pm && t.ps === ps && t.kind === kind && t.dag === dag);
    const addTie = (child, pm, ps, kind, dag, when) => tieOf(child, pm, ps, kind, dag) || TIES[TIES.push({ child, pm, ps, kind, dag, when, count: 0, flash: -1e9 }) - 1];
    for (const n of Object.keys(M)) for (const sf of F[n].machine.subflows || []) if (M[sf.flow]) addTie(sf.flow, n, sf.state, "declared", null, sf.when);
    const byTask = {};
    const indexTasks = () => { for (const k in byTask) delete byTask[k]; for (const m of Object.values(M)) for (const a of m.agents) if (a.task) (byTask[a.task] ||= []).push(a); };
    indexTasks();
    function parentOf(a) { // the session a new session was entered from: the deepest one still open then, else the task's in-progress session
      const t0 = start(a), sib = (byTask[a.task] || []).filter((b) => b !== a && b.m !== a.m);
      const open = sib.filter((b) => b.m !== IP && start(b) <= t0 && b.active >= t0 - 600).sort((x, y) => start(y) - start(x));
      const p = open[0] || sib.find((b) => b.m === IP);
      return p && { pm: p.m, ps: stateAt(p, t0) || p.trail[0]?.state || p.state };
    }
    for (const n of SUBS) for (const a of M[n].agents) { if (!a.task) continue; const p = parentOf(a); if (!p) continue;
      (tieOf(n, p.pm, p.ps, "declared", null) || addTie(n, p.pm, p.ps, "observed", null)).count++; }
    // a launch names its flow; where that is not a machine here, the skill it runs is
    for (const l of S.launches || []) { const fl = M[l.flow] ? l.flow : M[l.skill] ? l.skill : null; if (fl) addTie(fl, null, null, "dag", l.dag).count = M[fl].agents.filter((a) => !a.task).length; }
    const rank = (t) => (t.kind === "declared" ? 1e6 : t.kind === "observed" ? t.count : -1);
    const primary = {};
    for (const n of SUBS) { const ts = TIES.filter((t) => t.child === n && t.kind !== "dag").sort((a, b) => rank(b) - rank(a)); if (ts.length) primary[n] = ts[0]; }
    const others = (m) => TIES.filter((t) => t.child === m && t.kind === "observed" && primary[m] !== t);
    const dagTies = (m) => TIES.filter((t) => t.child === m && t.kind === "dag");
    const kidsAt = (m, s) => SUBS.filter((c) => primary[c] && primary[c].pm === m && primary[c].ps === s);
    const tied = SUBS.filter((c) => primary[c]), dagOnly = SUBS.filter((c) => !primary[c] && dagTies(c).length), dormant = SUBS.filter((c) => !primary[c] && !dagTies(c).length);
    const depthOf = (m) => (m === IP ? 0 : primary[m] ? 1 + depthOf(primary[m].pm) : 1);

    // ---- one machine as layers: breadth-first depth from its initial state, the longest-reaching path on row 0
    const tasksAt = (m, s) => M[m].agents.filter((a) => a.state === s && !a.move);
    function graph(m) {
      const mm = M[m], ids = mm.states.map((s) => s.id), init = initOf(m), depth = { [init]: 0 }, par = {}, q = [init];
      while (q.length) { const s = q.shift(); for (const t of mm.trans) if (t.source === s && !(t.target in depth)) { depth[t.target] = depth[s] + 1; par[t.target] = s; q.push(t.target); } }
      let md = Math.max(...Object.values(depth)); for (const id of ids) if (!(id in depth)) depth[id] = ++md;
      const ends = mm.states.filter((s) => s.final && s.id in depth).map((s) => s.id).sort((a, b) => depth[b] - depth[a]);
      const end = ends[0] ?? ids.reduce((a, b) => (depth[b] > depth[a] ? b : a));
      const main = new Set([init]); for (let s = end; s !== undefined; s = par[s]) main.add(s);
      const cols = []; for (const id of ids) (cols[depth[id]] ||= []).push(id);
      const row = {};
      for (const col of cols) { if (!col) continue; const mi = col.find((id) => main.has(id)), rest = col.filter((id) => id !== mi).sort((a, b) => M[m].agents.filter((x) => x.state === b).length - M[m].agents.filter((x) => x.state === a).length);
        if (mi !== undefined) row[mi] = 0; else row[rest.shift()] = 0;
        rest.forEach((id, i) => (row[id] = (i % 2 ? 1 : -1) * (Math.floor(i / 2) + 1))); }
      const rows = Object.values(row);
      return { init, depth, row, main, ncols: cols.length, rmin: Math.min(...rows), rmax: Math.max(...rows), order: ids.slice().sort((a, b) => depth[a] - depth[b] || row[a] - row[b]) };
    }
    const G = Object.fromEntries(Object.keys(M).map((m) => [m, graph(m)]));

    // ---- text: drawn at screen size and scaled by the browser text size, in the page's light face
    const wcache = new Map();
    const font = (px, wt = 300) => `${wt} ${px}px Inter, system-ui, sans-serif`;
    function textW(s, px, wt = 300) { const k = `${wt}|${px}|${s}`; if (!wcache.has(k)) { cx.font = font(px, wt); cx.letterSpacing = "0.6px"; wcache.set(k, cx.measureText(s).width); cx.letterSpacing = "0px"; } return wcache.get(k); }
    const PX = { main: () => 12.5 * FS, name: () => 12 * FS, sub: () => 10 * FS, bead: () => 11 * FS, dag: () => 10 * FS };
    const subLine = (m) => { const n = M[m].agents.length; return `${M[m].states.length} states · ${n} task${n === 1 ? "" : "s"}${seeded.has(m) ? " (seeded)" : ""}`; };

    // ---- the sky, laid out in canvas pixels so that at zoom 1 it fills the canvas exactly: nothing is ever off screen
    let L = null, W = 0, H = 0, DPR = 1, CW = 0, CH = 0, NX = 52;
    const key = (m, s) => `${m}:${s}`;
    const node = (m, s) => L.nodes.get(key(m, s));
    const planetOf = (m) => L.planets.find((p) => p.m === m);
    function addNode(m, s, x, y, planet) { const nd = { key: key(m, s), m, s, x, y, planet, final: isFinal(m, s), initial: initOf(m) === s, label: stName(m, s), r: 4 };
      L.nodes.set(nd.key, nd); return nd; }
    const fac = (m, dim) => (0.75 + 0.05 * M[m].states.length) * (dim ? 0.72 : 1);
    function layout() {
      L = { nodes: new Map(), planets: [], stars: [], tethers: [] };
      const g = G[IP], mx = 56 * FS, rowGap = clamp(CH * 0.075, 44, 80), colW = (CW - 2 * mx) / (g.ncols - 1);
      const labH = PX.name() * 1.3 + PX.sub() * 1.4 + 8, top0 = 10 * FS, starRoom = 26 * FS, bottom = 44, mainLab = 24 * FS, gapMin = 30 * FS, pad = 28 * FS, m0 = 14 * FS;
      const band = (g.rmax - g.rmin) * rowGap + 2 * mainLab;
      // every other machine is a planet in one of two bands, above and below the in-progress line, so neither band nor corner is left empty:
      // a tied machine hangs below the state it is entered from; the machines only DAGs launch and the idle ones (dimmed) fill the other slots
      const free = [...dagOnly.map((m) => ({ m, kind: "dag" })), ...dormant.map((m) => ({ m, kind: "idle", dim: true }))];
      const nLow = Math.max(tied.length, Math.ceil((tied.length + free.length) / 2));
      const lowFree = free.splice(free.length - Math.max(0, nLow - tied.length)), up = free;
      const low = tied.map((m) => ({ m, kind: "tied" })).concat(lowFree);
      const fMax = (list) => Math.max(0, ...list.map((o) => fac(o.m, o.dim)));
      const fU = fMax(up), fL = fMax(low), sumF = (list) => list.reduce((a, o) => a + fac(o.m, o.dim), 0);
      // planets as large as the height and both bands' widths allow; a name wider than its ring widens its slot
      const wOf = (o, s) => Math.max(2 * s * fac(o.m, o.dim) + pad, textW(o.m, PX.name(), 400) + pad);
      const avail = CW - 2 * m0, fits = (list, s) => list.reduce((a, o) => a + wOf(o, s), 0) <= avail;
      const sH = (CH - top0 - (up.length ? starRoom + labH : 0) - band - 2 * gapMin - (low.length ? labH : 0) - bottom) / (2 * fU + 2 * fL || 1);
      const sW = Math.min(...[up, low].filter((l) => l.length).map((l) => (avail - l.length * pad) / (2 * sumF(l))));
      let sc = clamp(Math.min(sH, sW), 18, 150); while (sc > 18 && !(fits(up, sc) && fits(low, sc))) sc *= 0.96;
      const yUp = top0 + starRoom + sc * fU, upBottom = up.length ? yUp + sc * fU + labH : top0, yLow = CH - bottom - (low.length ? labH + sc * fL : 0);
      const bandTop = (upBottom + (low.length ? yLow - sc * fL : CH - bottom)) / 2 - band / 2, yMain = bandTop + mainLab - g.rmin * rowGap;
      for (const st of M[IP].states) addNode(IP, st.id, mx + g.depth[st.id] * colW, yMain + g.row[st.id] * rowGap).col = RAMP[Math.round((g.depth[st.id] / (g.ncols - 1)) * (RAMP.length - 1))];
      // a band's planets share its spare width evenly
      const spread = (list, y) => { const ws = list.map((o) => wOf(o, sc)), gap = (avail - ws.reduce((a, w) => a + w, 0)) / (list.length + 1); let x = m0 + gap;
        return list.map((o, i) => { const it = { ...o, R: sc * fac(o.m, o.dim), w: ws[i], x: x + ws[i] / 2, y }; x += ws[i] + gap; return it; }); };
      // below, the tied machines keep the order of the states they hang from (a machine entered from a planet beside that planet), and each
      // free machine takes the place that moves the tied ones least from under their states
      const wantOf = (c) => (depthOf(c) === 1 ? node(primary[c].pm, primary[c].ps).x : wantOf(primary[c].pm) + 0.01 * depthOf(c));
      let order = low.filter((o) => o.kind === "tied").sort((a, b) => wantOf(a.m) - wantOf(b.m));
      for (const o of lowFree) { let best = null;
        for (let i = 0; i <= order.length; i++) { const cand = [...order.slice(0, i), o, ...order.slice(i)], pos = spread(cand, yLow);
          const cost = pos.reduce((a, it) => a + (it.kind === "tied" ? Math.abs(it.x - wantOf(it.m)) : 0), 0); if (!best || cost < best.cost) best = { cost, cand }; }
        order = best.cand; }
      const top = spread(up, yUp), lowIt = spread(order, yLow);
      for (const it of [...top, ...lowIt]) {
        const p = { m: it.m, x: it.x, y: it.y, R: it.R, dim: !!it.dim, kind: it.kind, beads: [], u: 0 }, g2 = G[it.m];
        const bw = 1.75 * p.R, rh = Math.min(0.42 * p.R, (1.15 * p.R) / Math.max(1, g2.rmax - g2.rmin)), rmid = (g2.rmin + g2.rmax) / 2;
        g2.order.forEach((s, i) => { const th = -Math.PI / 2 + (i * TAU) / g2.order.length, b = addNode(it.m, s, 0, 0, p);
          Object.assign(b, { rx: p.x + p.R * Math.cos(th), ry: p.y + p.R * Math.sin(th), fx: p.x - bw / 2 + (g2.depth[s] * bw) / Math.max(1, g2.ncols - 1), fy: p.y + (g2.row[s] - rmid) * rh,
            col: RAMP[Math.round((i / g2.order.length) * (RAMP.length - 1))] }); b.x = b.rx; b.y = b.ry; p.beads.push(b); });
        L.planets.push(p);
      }
      for (const c of tied) L.tethers.push({ t: primary[c], to: planetOf(c) });
      // a DAG is a star on the upper flank of each machine it launches; board-autopilot's stands before in-progress's start
      for (const p of L.planets) dagTies(p.m).forEach((t, k) => { const a = -2.35 + k * 0.42; L.stars.push({ t, dag: t.dag, child: p.m, host: p, a, x: p.x + (p.R + 16 * FS) * Math.cos(a), y: p.y + (p.R + 16 * FS) * Math.sin(a) }); });
      const s0 = node(IP, initOf(IP)); dagTies(IP).forEach((t, k) => L.stars.push({ t, dag: t.dag, child: IP, x: s0.x, y: s0.y - 44 * FS - k * 22 * FS }));
    }
    const unfold = () => smooth((view.k - 1.15) / 1.3); // every planet opens together as the view zooms in
    function place() {
      for (const p of L.planets) { p.u = unfold(p); for (const b of p.beads) { b.x = lerp(b.rx, b.fx, p.u); b.y = lerp(b.ry, b.fy, p.u); } }
      for (const n of L.nodes.values()) { const c = tasksAt(n.m, n.s).length; n.r = n.planet ? (2.8 + 0.9 * Math.sqrt(c)) * clamp(n.planet.R / 90, 1, 1.4) * (1 - 0.45 * n.planet.u) : 8 + 2.2 * Math.sqrt(c); }
    }

    // ---- view: zoom 1 is the fit; the wheel zooms about the cursor and the view never leaves the sky
    let view = { k: 1, x: 0, y: 0 }, anim = null, focus = null, pinned = null, hover = null;
    const clampView = (v) => { const k = clamp(v.k, 1, KMAX); return { k, x: clamp(v.x, CW - CW * k, 0), y: clamp(v.y, CH - CH * k, 0) }; };
    const toScreen = (x, y) => ({ x: NX + view.x + x * view.k, y: view.y + y * view.k });
    const toWorld = (sx, sy) => ({ x: (sx - NX - view.x) / view.k, y: (sy - view.y) / view.k });
    const centreOf = (v) => ({ x: (CW / 2 - v.x) / v.k, y: (CH / 2 - v.y) / v.k });
    const viewAt = (c, k) => clampView({ k, x: CW / 2 - c.x * k, y: CH / 2 - c.y * k });
    function zoomAt(sx, sy, k) { anim = null; const w = toWorld(sx, sy); k = clamp(k, 1, KMAX); view = clampView({ k, x: sx - NX - w.x * k, y: sy - w.y * k }); }
    function flyTo(c, k, ms = 600) { const c0 = centreOf(view), k0 = view.k, t0 = performance.now();
      anim = (now) => { const u = ease(clamp((now - t0) / ms, 0, 1)); view = viewAt({ x: lerp(c0.x, c.x, u), y: lerp(c0.y, c.y, u) }, Math.exp(lerp(Math.log(k0), Math.log(k), u))); if (u >= 1) anim = null; }; }
    const flyPlanet = (p, ms) => { focus = p.m; syncUrl(); flyTo({ x: p.x, y: p.y + 0.12 * p.R }, clamp((0.34 * Math.min(CW, CH)) / p.R, 1, KMAX), ms); };
    const fit = () => { focus = null; syncUrl(); flyTo({ x: CW / 2, y: CH / 2 }, 1); };

    // ---- labels: in-progress names first, then planet names, then the states of an unfolding planet; one that would
    // overprint another waits for more zoom rather than being drawn on top
    const hits = (a, b) => (b.r ? Math.hypot(Math.max(a.x0 - b.x, 0, b.x - a.x1), Math.max(a.y0 - b.y, 0, b.y - a.y1)) < b.r : a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1);
    let labels = [];
    function placeLabels() {
      labels = []; const placed = [], X0 = NX + 4, X1 = NX + CW - 4;
      const box = (p, r) => placed.push({ x: p.x, y: p.y, r });
      // the clock and the corner controls float over the sky: no label sits under them
      for (const e of [clockEl, zoomEl, revEl]) { const b = e.getBoundingClientRect(); if (b.width) placed.push({ x0: b.left - 6, x1: b.right + 6, y0: b.top - 4, y1: b.bottom + 4 }); }
      const orbit = (n) => { const c = tasksAt(n.m, n.s).length; return (c ? slot(n, c - 1).R + dotR() : n.r) * view.k + 2; };
      // a state blocks its own orbit of tasks, a folded planet its whole ring, a DAG star its glyph
      for (const n of L.nodes.values()) { if (n.planet && n.planet.u < 0.35) continue; box(toScreen(n.x, n.y), orbit(n)); }
      for (const p of L.planets) if (p.u < 0.35) box(toScreen(p.x, p.y), (p.R + 4 / view.k ** 0.6) * view.k);
      for (const s of L.stars) box(toScreen(s.x, s.y), 7);
      const put = (cands, w, h, lab) => { for (const c of cands) { const r = { x0: c.x, y0: c.y, x1: c.x + w, y1: c.y + h };
          if (r.x0 < X0 || r.x1 > X1 || r.y0 < 2 || r.y1 > H - 34) continue; const pad = { x0: r.x0 - 8, x1: r.x1 + 8, y0: r.y0 - 1, y1: r.y1 + 1 };
          if (placed.some((q) => hits(pad, q))) continue; placed.push(pad); labels.push({ ...lab, lead: c.lead, x: r.x0, y: r.y0 + h / 2, w, h }); return true; } return false; };
      // above and below try centred, then flush to either edge of the orbit, before a side
      const sides = (p, rr, w, h, order) => order.flatMap((sd) => { const xs = [p.x - w / 2, p.x + rr - w, p.x - rr];
        return sd === "below" ? xs.map((x) => ({ x, y: p.y + rr + 3 })) : sd === "above" ? xs.map((x) => ({ x, y: p.y - rr - 3 - h }))
          : sd === "right" ? [{ x: p.x + rr + 5, y: p.y - h / 2 }] : [{ x: p.x - rr - 5 - w, y: p.y - h / 2 }]; });
      const order = (g, s) => (g.row[s] < 0 ? ["above", "right", "left", "below"] : g.row[s] > 0 ? ["below", "right", "left", "above"] : g.depth[s] % 2 ? ["above", "below", "right", "left"] : ["below", "above", "right", "left"]);
      for (const n of L.nodes.values()) if (!n.planet) { const px = PX.main(), w = textW(n.label, px), h = px * 1.3, p = toScreen(n.x, n.y);
        // a crowded row (large text) takes a second tier, joined to its state by a hairline, before a name is dropped
        const rr = orbit(n), far = (dir, k) => [p.x - w / 2, p.x + rr - w, p.x - rr].map((x) => ({ x, y: dir > 0 ? p.y + rr + 3 + h * k : p.y - rr - 3 - h * (k + 1), lead: { x: p.x, y: p.y + dir * rr } }));
        const o = order(G[IP], n.s), d = o[0] === "above" ? -1 : 1; put([...sides(p, rr, w, h, o), ...[1.1, 2.2].flatMap((k) => [...far(d, k), ...far(-d, k)])], w, h, { node: n, px, a: 1 }); }
      for (const p of L.planets) { const px = PX.name(), sp = PX.sub(), c = toScreen(p.x, p.y), rr = p.R * view.k, w = Math.max(textW(p.m, px, 400), textW(subLine(p.m), sp)), h = px * 1.3 + sp * 1.4;
        put([{ x: c.x - w / 2, y: c.y + rr + 6 }, { x: c.x - w / 2, y: c.y - rr - 6 - h }], w, h, { planet: p, px, sp }); }
      for (const p of L.planets) if (p.u > 0.35) for (const b of p.beads) { const px = PX.bead(), w = textW(b.label, px), h = px * 1.3, c = toScreen(b.x, b.y);
        put(sides(c, orbit(b), w, h, order(G[p.m], b.s)), w, h, { node: b, px, a: smooth((p.u - 0.35) / 0.35) }); }
      for (const s of L.stars) { const px = PX.dag(), w = textW(s.dag, px), h = px * 1.3, c = toScreen(s.x, s.y);
        put([{ x: c.x - 9 - w, y: c.y - h / 2 }, { x: c.x + 9, y: c.y - h / 2 }, { x: c.x - w / 2, y: c.y - 9 - h }, { x: c.x - w / 2, y: c.y + 9 }], w, h, { star: s, px }); }
    }

    // ---- geometry shared by the flow lines, the moving tasks and the trace, so a highlight runs exactly where its line is
    let T = 0, last = performance.now();
    const hotM = () => (hover?.kind === "planet" ? hover.o.m : hover?.kind === "tether" ? hover.o.t.child : hover?.kind === "star" ? hover.o.child : hover?.kind === "node" && hover.o.planet ? hover.o.m : null);
    function curve(a, b, bend = 0.12) { const dx = b.x - a.x, dy = b.y - a.y; return { p0: a, p1: b, c: { x: (a.x + b.x) / 2 - dy * bend, y: (a.y + b.y) / 2 + dx * bend } }; }
    const edgeCurve = (s, q) => curve(s, q, q.x < s.x - 1 ? 0.28 : s.planet && s.planet.u < 0.5 ? 0.04 : 0.08);
    // a session entering a machine drops from the state it leaves and arrives from above; one from a planet runs across
    function entryPath(a, b) { if (a.planet) return curve(a, b, 0.1); const dy = b.y - a.y; return { cubic: true, p0: a, c1: { x: a.x, y: a.y + dy * 0.55 }, c2: { x: b.x, y: b.y - dy * 0.35 }, p1: b }; }
    function tetherPath(t, p) { const a = node(t.pm, t.ps); if (!a || !p) return null;
      if (!a.planet) return entryPath(a, { x: p.x, y: p.y - p.R });
      const ang = Math.atan2(a.y - p.y, a.x - p.x); return curve(a, { x: p.x + p.R * Math.cos(ang), y: p.y + p.R * Math.sin(ang) }, 0.1); }
    const at = (e, t) => { if (!e.cubic) { const u = 1 - t; return { x: u * u * e.p0.x + 2 * u * t * e.c.x + t * t * e.p1.x, y: u * u * e.p0.y + 2 * u * t * e.c.y + t * t * e.p1.y }; }
      const u = 1 - t; return { x: u ** 3 * e.p0.x + 3 * u * u * t * e.c1.x + 3 * u * t * t * e.c2.x + t ** 3 * e.p1.x, y: u ** 3 * e.p0.y + 3 * u * u * t * e.c1.y + 3 * u * t * t * e.c2.y + t ** 3 * e.p1.y }; };
    const trim = (e, ra, rb) => { const len = Math.hypot(e.p1.x - e.p0.x, e.p1.y - e.p0.y) || 1; return [Math.min(0.4, ra / len), 1 - Math.min(0.4, rb / len)]; };
    function along(e, t0, t1, n = 20) { cx.beginPath(); for (let i = 0; i <= n; i++) { const p = at(e, t0 + ((t1 - t0) * i) / n); i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y); } cx.stroke(); }
    // the page's flow line: a gradient from one end's colour to the other's, dashed, the dashes streaming the way it runs
    function flow(a, b, alpha, heat, d = [2, 5]) { const g = cx.createLinearGradient(a.x, a.y, b.x, b.y); g.addColorStop(0, rgba(a.col, alpha)); g.addColorStop(1, rgba(b.col, alpha));
      cx.strokeStyle = g; cx.lineWidth = (1.1 + heat * 1.5) / view.k; cx.setLineDash(d.map((v) => (v * 1.2) / view.k)); cx.lineDashOffset = (-T * 12 * 1.2) / view.k; }
    function arrow(p, q, col, len = 8) { len /= view.k; const a = Math.atan2(q.y - p.y, q.x - p.x); cx.fillStyle = col; cx.beginPath(); cx.moveTo(q.x, q.y);
      cx.lineTo(q.x - len * Math.cos(a - 0.4), q.y - len * Math.sin(a - 0.4)); cx.lineTo(q.x - len * Math.cos(a + 0.4), q.y - len * Math.sin(a + 0.4)); cx.fill(); }
    const heat = new Map(), heatOf = (k, now) => Math.max(0, 1 - (now - (heat.get(k) ?? -1e9)) / 2600);

    // ---- drawing
    function drawPlanets() { // no disc: a folded planet is its ring of states, with a faint dotted orbit that fades as it unfolds
      for (const p of L.planets) { const a = p.dim ? 0.7 : 1, hot = hotM() === p.m || focus === p.m, o = (hot ? 0.45 : 0.16) * (1 - smooth(p.u * 1.8)) * a; if (o < 0.01) continue;
        cx.strokeStyle = rgba(PLANET, o); cx.lineWidth = 1 / view.k; cx.setLineDash([1.5 / view.k, 4 / view.k]); cx.beginPath(); cx.arc(p.x, p.y, p.R, 0, TAU); cx.stroke(); cx.setLineDash([]); }
    }
    function drawEdges(now) {
      for (const m of Object.keys(M)) { const p = m === IP ? null : planetOf(m), a = p?.dim ? 0.7 : 1;
        for (const t of M[m].trans) { const s = node(m, t.source), q = node(m, t.target); if (!s || !q) continue;
          const hot = hover?.kind === "node" && (hover.o === s || hover.o === q), h = heatOf(`${s.key}>${q.key}`, now), e = edgeCurve(s, q), [t0, t1] = trim(e, s.r + 1 / view.k, q.r + 2 / view.k);
          flow(s, q, Math.min(1, (hot ? 0.95 : p ? lerp(0.3, 0.38, p.u) : 0.4) + h * 0.5) * a, h + (hot ? 0.8 : 0), p && p.u < 0.5 ? [1.5, 4] : [2, 5]);
          along(e, t0, t1, 16); cx.setLineDash([]); } }
    }
    function drawTethers(now) {
      const hm = hotM(), hs = hover?.kind === "node" && !hover.o.planet ? hover.o : null;
      const list = [...L.tethers.map((d) => ({ ...d, sec: false })), ...TIES.filter((t) => t.kind === "observed" && primary[t.child] !== t && (hm === t.child || focus === t.child || (hs && hs.m === t.pm && hs.s === t.ps)))
        .map((t) => ({ t, to: planetOf(t.child), sec: true }))];
      for (const d of list) { const e = tetherPath(d.t, d.to); d.e = e; if (!e) continue; const fl = Math.max(0, 1 - (now - d.t.flash) / 1600), hot = hm === d.t.child || (hover?.kind === "tether" && hover.o.t === d.t);
        const a = node(d.t.pm, d.t.ps), [t0] = trim(e, a.r + 2 / view.k, 0);
        flow(a, { ...e.p1, col: PLANET }, Math.min(1, (d.sec ? 0.4 : hot ? 0.95 : 0.55) + fl * 0.45), fl + (hot ? 0.8 : 0), d.t.kind === "observed" ? [1.5, 7] : [2, 5]);
        along(e, t0, 1, 24); cx.setLineDash([]); }
      L.drawnTies = list;
      for (const s of L.stars) { const tgt = s.host ? { x: s.host.x + s.host.R * Math.cos(s.a), y: s.host.y + s.host.R * Math.sin(s.a), col: PLANET } : node(IP, initOf(IP));
        const fl = Math.max(0, 1 - (now - s.t.flash) / 1600); flow({ x: s.x, y: s.y, col: DAGC }, tgt, (0.4 + fl * 0.55) * (s.host?.dim ? 0.7 : 1), fl, [1, 4]);
        cx.beginPath(); cx.moveTo(s.x, s.y); cx.lineTo(tgt.x, tgt.y); cx.stroke(); cx.setLineDash([]); }
    }
    function drawNodes() { // the page's state: a coloured rim and centre over a faint wash of its own colour, nothing dark behind it
      for (const n of L.nodes.values()) { const a = n.planet?.dim ? 0.7 : 1, hot = hover?.kind === "node" && hover.o === n;
        cx.fillStyle = rgba(n.col, (hot ? 0.3 : 0.12) * a); cx.beginPath(); cx.arc(n.x, n.y, n.r, 0, TAU); cx.fill();
        cx.strokeStyle = rgba(n.col, (hot ? 1 : 0.85) * a); cx.lineWidth = (hot ? 2 : n.planet ? 1.2 : 1.6) / view.k; cx.stroke();
        if (n.final) { cx.strokeStyle = rgba(n.col, 0.45 * a); cx.lineWidth = 1 / view.k; cx.beginPath(); cx.arc(n.x, n.y, n.r + 2.5 / view.k, 0, TAU); cx.stroke(); }
        cx.fillStyle = rgba(n.col, 0.9 * a); cx.beginPath(); cx.arc(n.x, n.y, Math.min((n.initial && !n.planet ? 3.2 : 1.8) / view.k, n.r * 0.4), 0, TAU); cx.fill(); }
    }
    function drawStar(s) { const r = 5.5 / view.k ** 0.5, hot = hover?.kind === "star" && hover.o === s, a = s.host?.dim ? 0.7 : 1;
      cx.fillStyle = rgba(DAGC, 0.12 * a); cx.beginPath(); cx.arc(s.x, s.y, r * 2, 0, TAU); cx.fill(); cx.fillStyle = rgba(DAGC, (hot ? 1 : 0.9) * a); cx.beginPath();
      for (let i = 0; i < 8; i++) { const rr = i % 2 ? r * 0.3 : r, th = (i * Math.PI) / 4 - Math.PI / 2; cx.lineTo(s.x + rr * Math.cos(th), s.y + rr * Math.sin(th)); } cx.closePath(); cx.fill(); }
    // tasks orbit the state they sit on; a moving task rides its flow line to the next state as a comet
    const dotR = () => 2.3 / view.k ** 0.6;
    function slot(n, i) { const sp = 5.8 / view.k ** 0.6, base = n.r + 4 / view.k ** 0.6; let rem = i, R = base;
      for (;;) { const cap = Math.max(6, Math.floor((TAU * R) / sp)); if (rem < cap) return { R, a: (rem / cap) * TAU }; rem -= cap; R += 5 / view.k ** 0.6; } }
    const taskPos = new Map();
    function pulse(x, y, u) { cx.strokeStyle = rgba(ACT, 0.7 * (1 - u)); cx.lineWidth = 1.2 / view.k; cx.beginPath(); cx.arc(x, y, (3 + 18 * u) / view.k ** 0.6, 0, TAU); cx.stroke(); }
    const moveCurve = (ag) => { const fr = ag.move.star || L.nodes.get(ag.move.from), to = node(ag.m, ag.state); if (!fr || !to) return null;
      return ag.move.star ? curve(fr, to, 0.18) : fr.m === ag.m ? (hasEdge(ag.m, fr.s, to.s) ? edgeCurve(fr, to) : curve(fr, to, 0.28)) : entryPath(fr, to); };
    function drawTasks(now) {
      taskPos.clear();
      for (const n of L.nodes.values()) { const a = n.planet?.dim ? 0.7 : 1;
        tasksAt(n.m, n.s).forEach((ag, i) => { const sl = slot(n, i), th = sl.a + T * 0.06, x = n.x + sl.R * Math.cos(th), y = n.y + sl.R * Math.sin(th);
          taskPos.set(ag, { x, y }); cx.fillStyle = rgba(TIER[tierOf(ag.model)], 0.9 * a); cx.beginPath(); cx.arc(x, y, dotR(), 0, TAU); cx.fill();
          if (ag.kind === "unattended") { cx.strokeStyle = "rgba(6,10,20,.9)"; cx.lineWidth = 0.8 / view.k; cx.stroke(); }
          if (now - (ag.landed || -1e9) < 1400) pulse(x, y, (now - ag.landed) / 1400); }); }
      for (const m of Object.values(M)) for (const ag of m.agents) if (ag.move) { const e = moveCurve(ag); if (!e) { ag.move = null; continue; }
        const u = clamp((now - ag.move.t0) / 1400, 0, 1), v = easeO(u), p = at(e, v);
        cx.strokeStyle = rgba(ACT, 0.55); cx.lineWidth = 1.6 / view.k; along(e, Math.max(0, v - 0.14), v, 8);
        cx.fillStyle = ACT; cx.beginPath(); cx.arc(p.x, p.y, dotR() * 1.5, 0, TAU); cx.fill(); taskPos.set(ag, p); if (u >= 1) { ag.move = null; ag.landed = now; } }
    }

    // ---- the trace: a task's path, in time order, across every machine it has a session in. Each hop is retraced along the
    // flow line it took, in the colours of its two states, all at once as on the Star Map; a hop the machine has no line
    // for bows off in red and dashed; an entry into a machine runs down its tether.
    let trace = null;
    function traceSegs(ag) {
      const list = (ag.task ? byTask[ag.task] || [ag] : [ag]).slice().sort((a, b) => start(a) - start(b)), segs = [];
      for (const s of list) {
        if (s.m !== IP && s.task) { const p = parentOf(s), a = p && node(p.pm, p.ps), b = node(s.m, initOf(s.m)); if (a && b) segs.push({ kind: "entry", a, b, at: start(s) - 0.5 }); }
        let from = initOf(s.m);
        for (const st of s.trail) { if (st.state !== from) { const a = node(s.m, from), b = node(s.m, st.state); if (a && b) segs.push({ kind: "hop", a, b, off: !hasEdge(s.m, from, st.state), at: st.at }); } from = st.state; }
      }
      return segs.sort((x, y) => x.at - y.at).map((s, i) => ({ ...s, n: i + 1 }));
    }
    const segCurve = (s) => (s.kind === "entry" ? entryPath(s.a, s.b) : s.off ? curve(s.a, s.b, 0.28) : edgeCurve(s.a, s.b));
    function badge(p, txt, col) { const px = 10 / view.k, w = Math.max(16, textW(txt, 10, 600) + 10) / view.k, h = 15 / view.k;
      cx.fillStyle = "rgba(6,10,20,0.92)"; cx.strokeStyle = rgba(col, 0.95); cx.lineWidth = 1.1 / view.k; cx.beginPath(); cx.roundRect(p.x - w / 2, p.y - h / 2, w, h, h / 2); cx.fill(); cx.stroke();
      cx.font = font(px, 600); cx.fillStyle = "#fef3c7"; cx.textAlign = "center"; cx.textBaseline = "middle"; cx.fillText(txt, p.x, p.y + 0.5 / view.k); }
    function drawTrace(now) {
      const src = hover?.kind === "task" ? hover.o : pinned; if (!src) return (trace = null);
      trace = { id: src.task || src.id };
      const segs = traceSegs(src), geo = [];
      trace.keys = new Set(segs.flatMap((s) => [s.a.key, s.b.key]));
      for (const s of segs) { const e = segCurve(s), [t0, t1] = trim(e, s.a.r + 2 / view.k, s.b.r + 4 / view.k); geo.push({ e, t0, t1, s });
        const col = s.off ? OFF : null, g = cx.createLinearGradient(s.a.x, s.a.y, s.b.x, s.b.y);
        g.addColorStop(0, rgba(col || s.a.col, 0.95)); g.addColorStop(1, rgba(col || (s.kind === "entry" ? s.b.col : s.b.col), 0.95));
        cx.strokeStyle = g; cx.lineWidth = 2.4 / view.k; cx.setLineDash(s.off ? [5 / view.k, 5 / view.k] : []); along(e, t0, t1, 24); cx.setLineDash([]);
        arrow(at(e, t1 - 0.02), at(e, t1), rgba(col || s.b.col, 0.95), 8); }
      // each state the path visits: its rim firms up
      for (const k of trace.keys) { const nd = L.nodes.get(k); if (!nd) continue; cx.strokeStyle = rgba(nd.col, 1); cx.lineWidth = 2 / view.k; cx.beginPath(); cx.arc(nd.x, nd.y, nd.r, 0, TAU); cx.stroke(); }
      // step numbers at each line's middle, a line taken twice carrying both, slid along it clear of the others
      const byLine = new Map(); geo.forEach((g) => { const k = `${g.s.a.key}>${g.s.b.key}>${g.s.kind}`; if (!byLine.has(k)) byLine.set(k, { g, nums: [] }); byLine.get(k).nums.push(g.s.n); });
      const taken = [];
      for (const { g, nums } of byLine.values()) { const txt = nums.join(" · "), w = (Math.max(16, textW(txt, 10, 600) + 10) + 4) / view.k, h = 19 / view.k;
        const p = [0.5, 0.38, 0.62, 0.28, 0.72].map((t) => at(g.e, lerp(g.t0, g.t1, t))).find((q) => !taken.some((o) => Math.abs(o.x - q.x) < w && Math.abs(o.y - q.y) < h)) || at(g.e, lerp(g.t0, g.t1, 0.5));
        taken.push({ x: p.x, y: p.y }); badge(p, txt, g.s.off ? OFF : ACT); }
      // the traced task's own dots, ringed
      for (const ag of src.task ? byTask[src.task] || [] : [src]) { const p = taskPos.get(ag); if (!p) continue; cx.strokeStyle = rgba(ACT, 0.95); cx.lineWidth = 1.4 / view.k; cx.beginPath(); cx.arc(p.x, p.y, 6 / view.k, 0, TAU); cx.stroke(); }
    }
    function text(s, x, y, px, col, align = "left", wt = 300) { cx.font = font(px, wt); cx.letterSpacing = "0.6px"; cx.fillStyle = col; cx.textAlign = align; cx.textBaseline = "middle"; cx.fillText(s, x, y); cx.letterSpacing = "0px"; }
    function drawLabels() {
      placeLabels(); const veil = pinned ? 0.4 : 1, lit = (n) => trace?.keys?.has(n.key);
      for (const l of labels) {
        if (l.planet) { const p = l.planet, hot = hotM() === p.m || focus === p.m, on = trace?.keys && p.beads.some(lit); cx.globalAlpha = (p.dim ? 0.75 : 1) * (on || hot ? 1 : veil);
          text(p.m, l.x + l.w / 2, l.y - l.h / 2 + l.px * 0.65, l.px, rgba(INK, hot || on ? 0.95 : 0.78), "center", 400); text(subLine(p.m), l.x + l.w / 2, l.y + l.h / 2 - l.sp * 0.7, l.sp, rgba(SUB, hot ? 0.8 : 0.55), "center"); cx.globalAlpha = 1; continue; }
        if (l.star) { cx.globalAlpha = (l.star.host?.dim ? 0.65 : 0.9) * veil; text(l.star.dag, l.x, l.y, l.px, DAGC); cx.globalAlpha = 1; continue; }
        const n = l.node, hot = (hover?.kind === "node" && hover.o === n) || lit(n); cx.globalAlpha = l.a * (n.planet?.dim ? 0.75 : 1) * (hot ? 1 : veil);
        if (l.lead) { const ty = l.lead.y > l.y ? l.y + l.h / 2 : l.y - l.h / 2; cx.strokeStyle = rgba(INK, 0.22); cx.lineWidth = 1; cx.beginPath(); cx.moveTo(l.lead.x, l.lead.y); cx.lineTo(l.lead.x, ty); cx.stroke(); }
        text(n.label, l.x, l.y, l.px, rgba(INK, hot ? 0.95 : n.planet ? 0.6 : 0.7), "left", kidsAt(n.m, n.s).length ? 400 : 300); cx.globalAlpha = 1; }
    }
    // the page's night sky, with its stars, so the zoom through from the Board is seamless
    function nightSky(now) { mcx.setTransform(DPR, 0, 0, DPR, 0, 0); const g = mcx.createRadialGradient(W * 0.5, H * 0.55, 0, W * 0.5, H * 0.55, Math.max(W, H) * 0.75);
      g.addColorStop(0, "#0e1628"); g.addColorStop(1, "#04060b"); mcx.fillStyle = g; mcx.fillRect(0, 0, W, H);
      for (const s of page.stars) { mcx.fillStyle = `rgba(200,215,240,${0.08 + 0.12 * (0.5 + 0.5 * Math.sin(now * 0.0006 + s.p))})`; mcx.beginPath(); mcx.arc(s.x * W, (((s.y * H + view.y * 0.06 * s.r) % H) + H) % H, s.r, 0, TAU); mcx.fill(); } }

    let sky = false, enter = null;
    function frame(now) {
      requestAnimationFrame(frame); if (!sky) return;
      const dt = Math.min(0.05, (now - last) / 1000); last = now; T += dt; if (anim) anim(now);
      place(); cx = bcx;
      cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, buf.width, buf.height);
      cx.setTransform(DPR * view.k, 0, 0, DPR * view.k, DPR * (NX + view.x), DPR * view.y);
      drawPlanets(); drawEdges(now); drawTethers(now); drawNodes(); L.stars.forEach(drawStar); drawTasks(now);
      // a pinned trace is the focused setting: the rest of the sky steps back under the page's dark veil
      if (pinned) { cx.setTransform(DPR, 0, 0, DPR, 0, 0); cx.fillStyle = "rgba(4,6,11,0.66)"; cx.fillRect(0, 0, W, H); cx.setTransform(DPR * view.k, 0, 0, DPR * view.k, DPR * (NX + view.x), DPR * view.y); }
      drawTrace(now);
      cx.setTransform(DPR, 0, 0, DPR, 0, 0); drawLabels();
      nightSky(now); mcx.setTransform(1, 0, 0, 1, 0, 0);
      if (!enter) mcx.drawImage(buf, 0, 0);
      else { // the page's zoom through: the Board blows up past the clicked point and fades while the sky grows out of it
        const q = Math.min(1, (now - enter.t0) / 520), e = ease(q), f = { x: enter.f.x * DPR, y: enter.f.y * DPR }, sN = 0.3 + 0.7 * e, sO = 1 + 2.5 * e;
        mcx.globalAlpha = e; mcx.drawImage(buf, f.x * (1 - sN), f.y * (1 - sN), buf.width * sN, buf.height * sN);
        mcx.globalAlpha = 1 - e; mcx.drawImage(enter.snap, f.x * (1 - sO) + NAVL * DPR * sO, f.y * (1 - sO), enter.snap.width * sO, enter.snap.height * sO); mcx.globalAlpha = 1; if (q >= 1) enter = null; }
      const pct = `${Math.round(view.k * 100)}%`; if (zoomEl.pct !== pct) { zoomEl.pct = pct; zoomEl.querySelector(".pct").textContent = pct; cv.classList.toggle("pan", view.k > 1.01); }
    }

    // ---- into and out of the sky: the page's go() still moves between levels; this layer takes over the In Progress one
    const cPage = document.getElementById("c"), SKY = [{ kind: "board" }, { kind: "state", id: "in_progress" }];
    const isSky = (p) => p.length === 2 && p[1].kind === "state" && p[1].id === "in_progress";
    function setSky(on) {
      if (on && !sky) pageLegend = legendEl.innerHTML;
      sky = on; document.body.classList.toggle("mv", on); legendEl.innerHTML = on ? skyLegend : pageLegend;
      if (on) { focus = null; resize(); } else { setHover(null); pinned = null; anim = null; }
      const q = new URLSearchParams(location.search); on ? q.set("level", "in_progress") : (q.delete("level"), q.delete("focus"), q.delete("pick")); history.replaceState(null, "", `?${q}`);
    }
    go = function (next, fx, fy, then) {
      const to = isSky(next);
      if (sky && !to) { // out: the page shrinks whatever its canvas shows, so it is handed the sky as it stands
        const pc = cPage.getContext("2d"); pc.setTransform(1, 0, 0, 1, 0, 0); pc.drawImage(cv, -NAVL * DPR, 0); setSky(false); return page.go(next, fx == null ? fx : fx - NAVL, fy, then); }
      if (!sky && to) {
        const snap = document.createElement("canvas"); snap.width = cPage.width; snap.height = cPage.height; snap.getContext("2d").drawImage(cPage, 0, 0);
        page.go(next, fx, fy, then); page.trans = null; page.mouse = null; document.getElementById("tip").style.opacity = 0; setSky(true); enter = { snap, f: { x: fx == null ? NAVL + (W - NAVL) / 2 : fx + NAVL, y: fy ?? H / 2 }, t0: performance.now() }; return; }
      return page.go(next, fx, fy, then);
    };
    const leave = (sx = NX + CW / 2, sy = H / 2) => go([{ kind: "board" }], sx, sy);
    // step out the way the page does: close the panel, then undo any zoom, then (at the fit) zoom out to the Board
    const back = (sx, sy) => (panel.classList.contains("open") ? closePanel() : view.k > 1.01 || focus ? fit() : leave(sx, sy));

    // ---- input: hover names and traces, click flies into a machine or pins a task, wheel zooms, drag pans
    function hit(sx, sy) {
      const w = toWorld(sx, sy), tol = 6 / view.k;
      for (const [ag, p] of taskPos) if (Math.hypot(p.x - w.x, p.y - w.y) < tol) return { kind: "task", o: ag };
      for (const s of L.stars) if (Math.hypot(s.x - w.x, s.y - w.y) < tol + 3 / view.k) return { kind: "star", o: s };
      for (const n of L.nodes.values()) if ((!n.planet || n.planet.u > 0.3) && Math.hypot(n.x - w.x, n.y - w.y) < n.r + tol) return { kind: "node", o: n };
      for (const l of labels) if (sx >= l.x && sx <= l.x + l.w && Math.abs(sy - l.y) < l.h / 2) return l.planet ? { kind: "planet", o: l.planet } : l.star ? { kind: "star", o: l.star } : { kind: "node", o: l.node };
      for (const p of L.planets) if (Math.hypot(p.x - w.x, p.y - w.y) < p.R + tol) return { kind: "planet", o: p };
      for (const d of L.drawnTies || []) { if (!d.e) continue; for (let i = 0; i <= 40; i++) { const q = at(d.e, i / 40); if (Math.hypot(q.x - w.x, q.y - w.y) < tol) return { kind: "tether", o: d }; } }
      return null;
    }
    const tieText = (t) => (t.kind === "declared" ? `opens from <b>${esc(stName(t.pm, t.ps))}</b> <span class="k">declared${t.when ? `, while ${esc(t.when)}` : ""}</span>`
      : `entered from <b>${esc(stName(t.pm, t.ps))}</b> <span class="k">${t.pm !== IP ? `on ${esc(t.pm)} · ` : ""}observed ×${t.count}</span>`);
    function tipHtml(h) {
      if (h.kind === "task") { const ag = h.o, oth = (byTask[ag.task] || []).filter((b) => b !== ag);
        return `<b>${esc(ag.task || ag.title)}</b> <span class="k">${esc(boardTitle[ag.task] || "")}</span><br>${esc(stName(ag.m, ag.state))} <span class="k">on ${esc(ag.m)} · ${hhmm(ag.active)}</span>` +
          (oth.length ? `<br><span class="k">also on</span> ${oth.map((b) => `${esc(b.m)} › ${esc(stName(b.m, b.state))}`).join(", ")}` : "") + `<div class="k">its path is traced in order · click to pin it</div>`; }
      if (h.kind === "node") { const n = h.o, ks = kidsAt(n.m, n.s), sec = TIES.filter((t) => t.pm === n.m && t.ps === n.s && primary[t.child] !== t && t.kind === "observed"), loops = M[n.m].all.filter((t) => t.source === n.s && t.target === n.s).map((t) => t.event);
        return `<b>${esc(n.label)}</b> <span class="k">${esc(n.m)} · ${tasksAt(n.m, n.s).length} tasks${n.final ? " · final" : ""}</span>` +
          [...ks.map((c) => primary[c]), ...sec].map((t) => `<br>${t.kind === "declared" ? "opens" : "enters"} <b>${esc(t.child)}</b> <span class="k">${t.kind === "declared" ? "declared" : `observed ×${t.count}`}</span>`).join("") +
          (loops.length ? `<div class="k">stays here on ${esc(loops.join(", ").toLowerCase())}</div>` : ""); }
      if (h.kind === "planet") { const m = h.o.m, p = primary[m], o = others(m), d = dagTies(m);
        return `<b>${esc(m)}</b> <span class="k">${esc(subLine(m))}</span>` + (p ? `<br>${tieText(p)}` : "") + o.map((t) => `<br>${tieText(t)}`).join("") +
          (d.length ? `<br>launched by <b>${d.map((t) => esc(t.dag)).join(", ")}</b>` : "") + (!p && !d.length ? `<br><span class="k">no tie this hour</span>` : "") +
          `<div class="k">${focus === m && view.k > 1.01 ? "wheel to zoom further · 0 or right-click to fit" : "click to fly in"}</div>`; }
      if (h.kind === "tether") { const t = h.o.t; return `<b>${esc(stName(t.pm, t.ps))}</b> <span class="k">(${esc(t.pm)})</span> → <b>${esc(t.child)}</b><br><span class="k">${t.kind === "declared" ? "declared: the state's flow opens it" : `observed: ${t.count} session${t.count === 1 ? "" : "s"} entered it while their task sat here`}</span>`; }
      if (h.kind === "star") { const t = h.o.t; return `<b>${esc(t.dag)}</b> <span class="k">DAG</span><br>launches ${esc(t.child)}${t.child === IP ? "" : ` <span class="k">· ${t.count} session${t.count === 1 ? "" : "s"} with no task</span>`}`; }
      return "";
    }
    function setHover(h, sx, sy) { hover = h; cv.classList.toggle("hot", !!h); if (!h) { tip.style.opacity = 0; return; } const html = tipHtml(h); if (tip.innerHTML !== html) tip.innerHTML = html; tip.style.opacity = 1;
      const r = tip.getBoundingClientRect(); tip.style.left = `${Math.min(sx + 14, W - r.width - 8)}px`; tip.style.top = `${Math.min(sy + 14, H - r.height - 8)}px`; }
    function openTask(ag) { pinned = ag; const all = byTask[ag.task] || [ag], colOf = (m) => planetOf(m)?.beads[0]?.col || RAMP[2];
      panel.innerHTML = `<span class="x">✕</span><h2>${esc(ag.task || ag.title)}</h2><div class="k">${esc(boardTitle[ag.task] || ag.title || "")}</div>
        <table>${all.map((b) => `<tr class="mrow"><td><i style="background:${colOf(b.m)}"></i>${esc(b.m)}</td><td>${esc(stName(b.m, b.state))}</td><td style="text-align:right;color:#6b7a93">${hhmm(b.active)}</td></tr>`).join("")}</table>
        <div class="k" style="margin-top:10px">path · ${traceSegs(ag).length} steps, in order</div><table class="trace">${traceSegs(ag).map((s) => `<tr><td>${s.n}</td><td>${s.kind === "entry" ? `<b>${esc(s.b.m)}</b> <span class="k">entered from ${esc(stName(s.a.m, s.a.s))}</span>` : `${esc(stName(s.a.m, s.a.s))} → ${esc(stName(s.b.m, s.b.s))} <span class="k">${esc(s.b.m)}</span>`}</td><td>${hhmm(s.at)}</td></tr>`).join("")}</table>`;
      panel.classList.add("open"); panel.querySelector(".x").onclick = closePanel; }
    function closePanel() { panel.classList.remove("open"); pinned = null; }
    let drag = null;
    cv.addEventListener("mousemove", (e) => { if (enter) return; if (drag) { anim = null; view = clampView({ k: view.k, x: drag.vx + e.clientX - drag.x, y: drag.vy + e.clientY - drag.y }); drag.moved ||= Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3; return; } setHover(hit(e.clientX, e.clientY), e.clientX, e.clientY); });
    cv.addEventListener("mouseleave", () => setHover(null));
    cv.addEventListener("mousedown", (e) => { if (e.button === 0 && view.k > 1.01) { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; cv.classList.add("drag"); } });
    addEventListener("mouseup", () => { cv.classList.remove("drag"); setTimeout(() => (drag = null)); });
    cv.addEventListener("click", (e) => { if (drag?.moved || enter) return; const h = hit(e.clientX, e.clientY);
      if (!h) return closePanel();
      if (h.kind === "task") return openTask(h.o);
      if (h.kind === "planet") return flyPlanet(h.o);
      if (h.kind === "node" && h.o.planet && h.o.planet.u < 0.5) return flyPlanet(h.o.planet);
      if (h.kind === "node" && !h.o.planet && kidsAt(IP, h.o.s).length) return flyPlanet(planetOf(kidsAt(IP, h.o.s)[0]));
      if (h.kind === "tether") return flyPlanet(h.o.to);
      if (h.kind === "star" && h.o.host) return flyPlanet(h.o.host); });
    cv.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!enter) back(e.clientX, e.clientY); });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); if (enter) return; zoomAt(e.clientX, e.clientY, view.k * Math.exp(-e.deltaY * 0.0015)); if (view.k <= 1.001) focus = null; setHover(hit(e.clientX, e.clientY), e.clientX, e.clientY); }, { passive: false });
    zoomEl.addEventListener("click", (e) => { const z = e.target.dataset?.z; if (z === undefined) return; if (z === "0") return fit(); flyTo(centreOf(view), clamp(view.k * (z === "1" ? 1.8 : 1 / 1.8), 1, KMAX), 320); });
    addEventListener("keydown", (e) => { if (!sky || e.target.tagName === "INPUT") return; let used = true;
      if (e.key === "0") fit(); else if (e.key === "Escape" || e.key === "Backspace") back();
      else if (e.key === "+" || e.key === "=") flyTo(centreOf(view), clamp(view.k * 1.8, 1, KMAX), 320); else if (e.key === "-") flyTo(centreOf(view), clamp(view.k / 1.8, 1, KMAX), 320); else used = false;
      if (used) { e.stopPropagation(); e.preventDefault(); } }, true);
    // navigator rows: a machine row flies to that machine in the sky (zooming in from the Board first); the In progress row refits
    document.getElementById("layers").addEventListener("click", (e) => { const b = e.target.closest(".node"), t = b?.querySelector(".t")?.textContent?.trim(); if (!b || e.target.classList.contains("chev")) return;
      const p = t && t !== IP && L && planetOf(t);
      if (sky && b.classList.contains("here")) { e.stopPropagation(); return fit(); }
      if (!p && t !== IP) return;
      e.stopPropagation(); if (!sky) go(SKY); setTimeout(() => (p ? flyPlanet(planetOf(t)) : fit()), sky ? 0 : 540); }, true);

    // ---- the address that reproduces the view, and the review-only text size switch
    function syncUrl() { const q = new URLSearchParams(location.search); focus ? q.set("focus", focus) : q.delete("focus"); q.delete("pick"); history.replaceState(null, "", `?${q}`); }
    function setFS(p) { document.documentElement.style.fontSize = p === 100 ? "" : `${p}%`; const q = new URLSearchParams(location.search); p === 100 ? q.delete("fs") : q.set("fs", p); history.replaceState(null, "", `?${q}`); dispatchEvent(new Event("resize")); }
    function renderRev() { const fs = Math.round(FS * 100); revEl.innerHTML = `review · text ` + [100, 125, 150].map((p) => `<button data-fs="${p}" class="${p === fs ? "on" : ""}">${p}%</button>`).join("");
      revEl.querySelectorAll("[data-fs]").forEach((b) => (b.onclick = () => setFS(+b.dataset.fs))); }
    function resize() { DPR = devicePixelRatio || 1; NX = NAVW(); W = innerWidth - RAILW(); H = innerHeight; CW = W - NX; CH = H;
      for (const c of [cv, buf]) { c.width = W * DPR; c.height = H * DPR; } cv.style.width = `${W}px`; cv.style.height = `${H}px`;
      readFS(); wcache.clear(); renderRev(); if (!sky && L) return; const c = focus && view.k > 1.01 ? planetOf(focus) : null; layout(); view = { k: 1, x: 0, y: 0 }; place(); if (c) flyPlanet(planetOf(c.m), 1); }

    // ---- activity: replay what the snapshot holds, then simulate moves, sub-machine entries and DAG launches
    let simT = S.now, seq = 0;
    const lines = [];
    for (const m of Object.values(M)) for (const a of m.agents) for (const s of a.trail) lines.push({ at: s.at, html: `<b>${esc(a.task || a.id.slice(0, 8))}</b> ${esc(s.event.toLowerCase())} <em>${esc(m.name)}</em>` });
    lines.sort((a, b) => b.at - a.at); lines.length = Math.min(lines.length, 40);
    const renderClock = () => (clockEl.innerHTML = `<i></i>simulated · ${hhmm(simT)} MST`);
    const renderFeed = () => { feed.innerHTML = lines.map((l) => `<div${l.fresh ? ' class="new"' : ""}><em>${hhmm(l.at)}</em> ${l.html}</div>`).join(""); lines.forEach((l) => (l.fresh = false)); };
    const log = (html) => { lines.unshift({ at: simT, html, fresh: true }); lines.length = Math.min(lines.length, 40); renderFeed(); renderClock(); };
    const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
    function moveTo(ag, to, event, fromKey, star) { const from = fromKey || key(ag.m, ag.state); ag.move = { from, star, t0: performance.now() }; heat.set(`${from}>${key(ag.m, to)}`, performance.now());
      ag.state = to; ag.trail.push({ state: to, event, at: simT }); ag.trail = ag.trail.slice(-12); ag.active = simT; ag.steps = (ag.steps || 0) + 1;
      if (isFinal(ag.m, to) && ag.m !== IP) ag.doneAt = performance.now(); }
    const spare = (t) => M[t.pm].agents.filter((a) => a.state === t.ps && a.task && !a.move && !M[t.child].agents.some((b) => b.task === a.task));
    function simStep() {
      simT += 45; const r = Math.random();
      if (r < 0.22) { // a task's session enters a sub-machine from the state it sits on
        const ts = TIES.filter((t) => t.kind !== "dag" && spare(t).length), t = ts.length && pick(ts);
        if (t) { const p = pick(spare(t)), ag = { id: `sim-${++seq}`, title: p.title, model: p.model, kind: p.kind || "interactive", badges: [], task: p.task, m: t.child, state: initOf(t.child), steps: 0, trail: [], active: simT, sim: true };
          M[t.child].agents.push(ag); indexTasks(); moveTo(ag, initOf(t.child), "ENTERED", key(t.pm, t.ps)); if (t.kind === "observed") t.count++; t.flash = performance.now();
          log(`<b>${esc(p.task)}</b> entered <em>${esc(t.child)}</em> from ${esc(stName(t.pm, t.ps).toLowerCase())}`); return; } }
      if (r < 0.3) { const ss = L.stars.filter((s) => s.child !== IP), s = ss.length && pick(ss);
        if (s) { const ag = { id: `sim-${++seq}`, title: "unattended run", model: "standard", kind: "unattended", badges: [], task: null, m: s.child, state: initOf(s.child), steps: 0, trail: [], active: simT, sim: true };
          M[s.child].agents.push(ag); moveTo(ag, initOf(s.child), "LAUNCHED", null, s); s.t.count++; s.t.flash = performance.now(); log(`<b>${esc(s.dag)}</b> launched <em>${esc(s.child)}</em>`); return; } }
      const pool = Object.values(M).flatMap((m) => m.agents).filter((a) => !a.move && !isFinal(a.m, a.state) && M[a.m].trans.some((t) => t.source === a.state));
      const weighted = pool.filter((a) => a.m !== IP || Math.random() < 0.35), ag = pick(weighted.length ? weighted : pool); if (!ag) return;
      const t = pick(M[ag.m].trans.filter((x) => x.source === ag.state)); moveTo(ag, t.target, t.event);
      log(`<b>${esc(ag.task || ag.id.slice(0, 8))}</b> ${esc(t.event.toLowerCase())} <em>${esc(ag.m)}</em>`);
    }
    function retire() { const now = performance.now(); for (const m of Object.values(M)) { const gone = m.agents.filter((a) => a.sim && a.doneAt && now - a.doneAt > 9000 && a !== pinned);
      if (gone.length) { if (primary[m.name]) primary[m.name].flash = now; m.agents = m.agents.filter((a) => !gone.includes(a)); indexTasks(); } } }
    setInterval(() => { if (document.hidden || !sky) return; simStep(); retire(); }, 1700);

    // ---- start where the address says: the Board by default, the sky for &level=in_progress, &focus= or &pick=
    const want = P.get("level") === "in_progress" || P.get("focus") || P.get("pick");
    if (want && !isSky(page.stack)) { page.go(SKY); page.trans = null; }
    else if (!want && !P.get("level") && page.stack.length !== 1) { page.go([{ kind: "board" }]); page.trans = null; }
    resize(); renderFeed(); renderClock(); addEventListener("resize", resize); document.fonts?.ready.then(() => { wcache.clear(); resize(); });
    setSky(isSky(page.stack));
    const f0 = P.get("focus"); if (sky && f0 && planetOf(f0)) flyPlanet(planetOf(f0), 1);
    if (sky && P.get("pick") === "busy") { const t = Object.entries(byTask).sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1))[0]; if (t) openTask(t[1].find((a) => a.m !== IP) || t[1][0]); }
    requestAnimationFrame(frame);
  }
})();
