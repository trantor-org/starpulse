"use strict";
/*
  Design review only: the In Progress level as a ledger, over the saved snapshot in data.js. It opens the way the live
  level does: from the Board, clicking the In progress galaxy zooms through into it, and right-click, Escape or
  Backspace at the top zooms back out. The in-progress machine stays fixed across the top as the template; every other
  lifecycle machine is a row under it, its own states in one line from first to last with its tasks on them, hung from
  the template state it is entered from (a notch under that state's column, in its colour: filled when the state's flow:
  declares it, hollow when only the trails show it). A DAG is a star at the head of the row it launches.

  Nesting: a row is only a machine entered from the one at the top. A machine with machines entered from it says how
  many on its name line; clicking anywhere on its row zooms through, that machine takes the top and its machines
  become the rows, with a breadcrumb back up. Escape steps back out one machine at a time. A row stands for everything
  nested under it: stuck work anywhere below marks it and names where, and its entries land on its ticks in the strip.

  Rows run newest activity first; one sequence, so the rows in view are one span of time; a row with a task stuck
  over 2 h is marked red in its place. The wheel, PgUp/PgDn, Home/End and the thumb scroll them, 20 loaded at a time as the footer comes into view, as the DAG ledger
  does; a 24 h strip of machine entries runs along the bottom with the rows in view shaded. Flow lines are the page's own:
  a dashed gradient between the colours of the two states, streaming the way the flow runs. Hovering a row draws its tie;
  hovering a task retraces its path in order, across every machine it has a session in, along those same lines; clicking
  it pins the trace and opens the panel. &level=in_progress opens on the ledger, &fs=125 or &fs=150 sets the browser text
  size, &open=<machine> opens drilled into that machine, &focus=<machine> opens scrolled to that row (opening its parent first), &pick=busy pins the task on the most machines at once, &many=N seeds
  N more machines (24 by default, 0 for the snapshot alone), and &fan=N (3 to 8) widens the branch at Checkpointed and Red
  proven to N states on one level, in the template and in the triaging-alerts row, to show a wide machine: a column of
  three or more states names them beside it and takes the width its names need. running-skill-evals had no session in the saved snapshot, so
  two are seeded from the live shape (a task drafting a skill asks for a run); seeded rows say so.
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
    // review option: how a row shows where its nesting is (&nest=mini|chain|tray|ghost), each in place of the badge; badge is the approved `N nested ›` alone
    const NESTS = ["badge", "mini", "chain", "tray", "ghost"];
    let NESTV = NESTS.includes(P.get("nest")) ? P.get("nest") : "badge";
    const readFS = () => (FS = parseFloat(getComputedStyle(document.documentElement).fontSize) / 16 || 1);
    const NAVW = () => parseInt(getComputedStyle(document.documentElement).getPropertyValue("--nav")) || 52, RAILW = () => document.getElementById("rail").offsetWidth;

    // ---- page chrome: the live page's hover navigator and rail stay; in the sky this layer's canvas, clock, feed and legend stand in
    const css = document.createElement("style");
    css.textContent = `
      body.mv #c, body.mv #clock, body.mv #feed { display: none; }
      body:not(.mv) #mv, body:not(.mv) #mvtip, body:not(.mv) #mvclock, body:not(.mv) #mvfeed { display: none; }
      #mv { position: fixed; left: 0; top: 0; display: block; cursor: default; } #mv.pan { cursor: grab; } #mv.drag { cursor: grabbing; } #mv.hot { cursor: pointer; }
      #mvtip { position: fixed; z-index: 4; pointer-events: none; padding: .5rem .7rem; border-radius: 8px; font-size: .75rem; line-height: 1.5; max-width: 26rem;
        background: rgba(12,19,34,.94); border: 1px solid rgba(148,163,184,.18); backdrop-filter: blur(6px); opacity: 0; transition: opacity .12s; color: #dbe4f3; }
      #mvtip .k { color: #6b7a93; font-size: .6875rem; } #mvtip b { font-weight: 500; }
      #mvclock { position: fixed; z-index: 4; top: 18px; right: calc(var(--rail) + 24px); font: .65625rem "JetBrains Mono", ui-monospace, monospace; color: #fbbf24; pointer-events: none; text-shadow: 0 0 6px #04060b, 0 0 12px #04060b; }
      #mvclock i { display: inline-block; width: 5px; height: 5px; border-radius: 50%; background: #fbbf24; margin-right: 6px; vertical-align: 1px; }
      body:has(#panel.open) #mvclock { opacity: 0; }
      #mvrev { position: fixed; z-index: 4; bottom: 14px; display: flex; gap: 2px; align-items: center; font-size: .6875rem; color: #3f4c66; text-shadow: 0 0 6px #04060b, 0 0 12px #04060b; }
      #mvrev { left: calc(var(--nav) + 18px); }
      #mvrev button { all: unset; cursor: pointer; padding: .15rem .5rem; border-radius: 5px; color: #6b7a93; }
      #mvrev button:hover { color: #dbe4f3; background: rgba(148,163,184,.08); } #mvrev button.on { color: #fbbf24; }
      #mvfeed { font: 10.5px/1.75 "JetBrains Mono", ui-monospace, monospace; flex: 1; min-height: 0; overflow: hidden; }
      #mvfeed div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } #mvfeed b { font-weight: 400; color: #dbe4f3; } #mvfeed em { font-style: normal; opacity: .6; }
      #mvfeed div.new { animation: flash 1.2s; }
      #mvtop { position: fixed; z-index: 4; transform: translateX(-50%); padding: .2rem .75rem; border-radius: 999px; font-size: .6875rem; color: #dbe4f3; cursor: pointer;
        background: rgba(12,19,34,.92); border: 1px solid rgba(167,139,250,.35); display: none; } #mvtop:hover { border-color: rgba(167,139,250,.7); } body:not(.mv) #mvtop { display: none !important; }
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
    const revEl = el("mvrev"), topEl = el("mvtop", "↑ back to newest");
    const panel = document.getElementById("panel"), legendEl = document.getElementById("legend");
    const feed = Object.assign(document.createElement("div"), { id: "mvfeed" }); document.getElementById("feed").after(feed);
    const dash = (a, b, w = 1.2) => `<i style="background:linear-gradient(90deg,${a},${b});border-radius:0;height:${w}px;width:16px;vertical-align:3px"></i>`;
    const skyLegend = `<h3>Legend</h3>
      <span><i style="background:${TIER.deep}"></i>deep</span><span><i style="background:${TIER.standard}"></i>standard</span><span><i style="background:${TIER.other}"></i>other</span><br>
      <span style="color:${RAMP[2]}">▼</span> declared entry <span style="color:${RAMP[2]};margin-left:8px">▽</span> observed<br>
      <span style="color:${DAGC}">✦</span> DAG <span style="margin-left:10px">${dash(RAMP[1], RAMP[5], 2.4)}task path</span><br>
      <span><i style="background:${OFF};border-radius:0;width:2px"></i>stuck over 2 h</span><br>
      <span style="color:${PLANET}">›</span> click any row to open it<br>
      <span><i style="background:${ACT};box-shadow:0 0 6px ${ACT}"></i>activity now</span>`;
    let pageLegend = legendEl.innerHTML;

    // ---- the machines: in-progress and every other lifecycle machine, self-loops dropped (the tooltip names them)
    const M = {};
    for (const n of Object.keys(F)) if (n !== "board") {
      const f = F[n];
      M[n] = { name: n, states: f.machine.states, all: f.machine.transitions, trans: f.machine.transitions.filter((t) => t.source !== t.target),
        agents: f.agents.map((a) => ({ ...a, trail: [...(a.trail || [])], m: n })) };
    }
    // &fan=N widens the template's column after Worktree ready to N states, as if more paths branched there beside Checkpointed and
    // Red proven, each rejoining at Checkpointed; tasks waiting at Checkpointed are spread across them so their orbits show
    const FAN = Math.min(8, Math.max(0, +P.get("fan") || 0)), FANS = ["Spike run", "Repro written", "Design asked", "Deps pinned", "Spec drafted", "Data migrated"];
    if (FAN > 2 && M[IP]) { const add = FANS.slice(0, FAN - 2).map((name) => ({ id: name.toLowerCase().replace(/ /g, "_"), name })), mm = M[IP];
      mm.states = [...mm.states]; mm.states.splice(mm.states.findIndex((x) => x.id === "checkpointed"), 0, ...add);
      for (const x of add) mm.trans.push({ source: "worktree_ready", target: x.id, event: "BRANCHED" }, { source: x.id, target: "checkpointed", event: "CHECKPOINTED" });
      mm.agents.filter((a) => a.state === "checkpointed").forEach((a, i) => { if (i % 3 === 2) return; const x = add[i % add.length]; a.state = x.id; a.trail.push({ state: x.id, event: "BRANCHED", at: a.active }); }); }
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
    // seed more lifecycles so the ledger shows the 20+ case: short machines of the live shape, their sessions taken from
    // in-progress tasks and timed across the last day; a few idle for hours, two with a task stuck past 2 h
    const MANY = P.get("many") == null ? 24 : Math.max(0, +P.get("many") || 0);
    const NAMES = ["reviewing-prs", "authoring-tests", "verifying-claims", "querying-observability", "searching-code", "operating-unraid", "designing-ui",
      "briefing-subagents", "simplifying-implementations", "auditing-code", "authoring-docs", "rotating-secrets", "backing-up-postgres", "pruning-worktrees",
      "tuning-dashboards", "migrating-schemas", "renewing-certs", "triaging-alerts", "reconciling-board", "benchmarking-models", "curating-memory",
      "drafting-adrs", "replaying-trails", "sweeping-scratch", "probing-endpoints", "restoring-backups", "linting-docs", "watching-ci"];
    const SHAPES = [["started", "gathered", "drafted", "checked", "done"], ["queued", "running", "reviewed", "merged"], ["asked", "planned", "applied", "verified", "closed"],
      ["opened", "probed", "diagnosed", "fixed", "proved", "closed"]];
    const NEST = { "verifying-claims": ["running-skill-evals", "old"], "benchmarking-models": ["running-skill-evals", "new"], "authoring-docs": ["authoring-skills", "new"] };
    let rs = 3015; const rnd = () => (rs = (rs * 1103515245 + 12345) % 2147483648) / 2147483648;
    const ipTasks = (M[IP]?.agents || []).filter((a) => a.task && a.trail.length);
    for (let i = 0; i < Math.min(MANY, NAMES.length) && ipTasks.length; i++) {
      const n = NAMES[i], sh = [...SHAPES[i % SHAPES.length]], cap = (s) => s[0].toUpperCase() + s.slice(1);
      const states = sh.map((id, k) => ({ id, name: cap(id), initial: !k, final: k === sh.length - 1 })), trans = sh.slice(1).map((id, k) => ({ source: sh[k], target: id, event: id.toUpperCase() }));
      if (FAN > 2 && n === "triaging-alerts") { const br = ["paged", "silenced", "muted", "escalated", "deduped", "snoozed", "rerouted", "acked"].slice(0, FAN);
        states.splice(1, states.length - 2, ...br.map((id) => ({ id, name: cap(id) }))); trans.length = 0;
        for (const b of br) trans.push({ source: sh[0], target: b, event: b.toUpperCase() }, { source: b, target: sh.at(-1), event: "CLOSED" }); sh.splice(1, sh.length - 2, ...br.slice(0, 1)); }
      else if (i % 3 === 1) { states.splice(2, 0, { id: "blocked", name: "Blocked" }); trans.push({ source: sh[1], target: "blocked", event: "BLOCKED" }, { source: "blocked", target: sh[2], event: "UNBLOCKED" }); }
      M[n] = { name: n, states, all: trans, trans, agents: [] }; SUBS.push(n); seeded.add(n);
      const kind = i % 7 === 3 ? "idle" : i === 1 || i === 9 ? "stuck" : "live", nA = n === "triaging-alerts" && FAN > 2 ? FAN : kind === "idle" ? 1 + (i % 2) : kind === "stuck" ? 2 : 1 + Math.floor(rnd() * 5);
      // a few are entered from another machine's sessions instead, so the ledger nests three deep: in-progress › authoring-skills ›
      // running-skill-evals › verifying-claims; one of them from the oldest session there, so stuck work sits two machines down
      const par = NEST[n] && M[NEST[n][0]]?.agents.filter((a) => a.task).sort((x, y) => x.active - y.active);
      if (par?.length) { for (let j = 0; j < 2; j++) { const p = NEST[n][1] === "old" ? par[0] : par[(par.length - 1 - j + par.length) % par.length], upto = NEST[n][1] === "old" ? 1 : Math.min(j + 1, sh.length - 2);
          const t0 = Math.min(p.active + 30 + j * 20, S.now - upto * 150 - 60), tr = []; for (let k = 0; k <= upto; k++) tr.push({ state: sh[k], event: k ? sh[k].toUpperCase() : "ENTERED", at: t0 + k * 150 });
          M[n].agents.push({ id: `seed-${n}-${j}`, title: p.title, model: p.model, kind: "interactive", badges: [], task: p.task, m: n, state: sh[upto], steps: tr.length, trail: tr, active: tr.at(-1).at }); }
        continue; }
      for (let j = 0; j < nA; j++) {
        const p = ipTasks[(i * 7 + j * 13) % ipTasks.length], age = kind === "idle" ? 3600 * (3 + rnd() * 18) : kind === "stuck" && !j ? 3600 * (2.5 + rnd() * 2) : 60 * (2 + rnd() * 80);
        const upto = kind === "idle" ? sh.length - 1 : Math.floor(rnd() * (sh.length - 1)), t0 = S.now - age - upto * 150, tr = [];
        for (let k = 0; k <= upto; k++) tr.push({ state: sh[k], event: k ? sh[k].toUpperCase() : "ENTERED", at: t0 + k * 150 });
        M[n].agents.push({ id: `seed-${n}-${j}`, title: p.title, model: p.model, kind: "interactive", badges: [], task: p.task, m: n, state: sh[upto], steps: tr.length, trail: tr, active: tr.at(-1).at });
      }
      // the fan machine's tasks wait one on each branch
      if (n === "triaging-alerts" && FAN > 2) M[n].agents.forEach((a, j) => { const b = M[n].states[1 + (j % FAN)].id; a.trail = [a.trail[0], { state: b, event: b.toUpperCase(), at: a.trail[0].at + 150 }];
        a.state = b; a.steps = 2; a.active = a.trail[1].at; });
    }

    // review case (&cr=1): triaging-cr-reviews's own three-way fork from start, each branch with machines entered from it, two and three deep
    const CR = P.get("cr") ? { "replying-threads": ["triaging-cr-reviews", "audit_active", ["drafted", "replied", "closed"]], "resolving-threads": ["replying-threads", "replied", ["queued", "resolved", "closed"]],
      "checking-bots": ["resolving-threads", "resolved", ["asked", "answered", "closed"]], "querying-reviews": ["triaging-cr-reviews", "audit_active", ["queried", "read", "done"]],
      "verifying-fixes": ["triaging-cr-reviews", "fix_verified", ["started", "proved", "done"]], "rerunning-ci": ["verifying-fixes", "proved", ["queued", "running", "green"]],
      "closing-reviews": ["triaging-cr-reviews", "completed", ["closing", "closed"]] } : {};
    if (P.get("cr") && ipTasks.length) { const cap = (x) => x.split("_").map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
      const ids = ["start", "audit_active", "dismissal_replied", "audit_recorded", "approval_requested", "fix_verified", "fix_replied", "completed"], fin = ["approval_requested", "completed"];
      const ev = [["start", "audit_active"], ["audit_active", "dismissal_replied"], ["dismissal_replied", "audit_active"], ["audit_active", "audit_recorded"], ["audit_recorded", "approval_requested"], ["start", "fix_verified"], ["fix_verified", "fix_replied"], ["fix_replied", "start"], ["start", "completed"]];
      const mk = (n, ids, trans, fins) => { M[n] = { name: n, states: ids.map((id, k) => ({ id, name: cap(id), initial: !k, final: fins.includes(id) })), all: trans, trans, agents: [] }; SUBS.push(n); seeded.add(n); };
      mk("triaging-cr-reviews", ids, ev.map(([a, b]) => ({ source: a, target: b, event: b.toUpperCase() })), fin);
      ["audit_active", "fix_verified", "completed"].forEach((st, j) => { const p = ipTasks[(j * 5 + 3) % ipTasks.length], t0 = S.now - 600 - j * 240, tr = [{ state: "start", event: "ENTERED", at: t0 }, { state: st, event: st.toUpperCase(), at: t0 + 150 }];
        M["triaging-cr-reviews"].agents.push({ id: `seed-cr-${j}`, title: p.title, model: p.model, kind: "interactive", badges: [], task: p.task, m: "triaging-cr-reviews", state: st, steps: 2, trail: tr, active: tr[1].at }); });
      for (const [n, [, , sh]] of Object.entries(CR)) mk(n, sh, sh.slice(1).map((id, k) => ({ source: sh[k], target: id, event: id.toUpperCase() })), [sh.at(-1)]); }

    // ---- ties: declared (a state's flow:), observed (the state a task held when its session entered), DAG launches
    const TIES = [];
    const tieOf = (child, pm, ps, kind, dag) => TIES.find((t) => t.child === child && t.pm === pm && t.ps === ps && t.kind === kind && t.dag === dag);
    const addTie = (child, pm, ps, kind, dag, when) => tieOf(child, pm, ps, kind, dag) || TIES[TIES.push({ child, pm, ps, kind, dag, when, count: 0, flash: -1e9 }) - 1];
    for (const n of Object.keys(M)) for (const sf of F[n]?.machine.subflows || []) if (M[sf.flow]) addTie(sf.flow, n, sf.state, "declared", null, sf.when);
    for (const [n, [pm, ps]] of Object.entries(CR)) if (M[n]) addTie(n, pm, ps, "declared", null);
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
    // ---- nesting: a machine sits under the machine its primary tie enters it from; untied machines, and a loop of ties, sit under the template
    const up = {};
    for (const m of SUBS) { const p = primary[m]?.pm; up[m] = p && p !== m && M[p] && p !== IP ? p : IP; }
    for (const m of SUBS) { let p = up[m], k = 0; while (p !== IP && p !== m && k++ < SUBS.length) p = up[p]; if (p === m) up[m] = IP; }
    const KIDS = Object.fromEntries([IP, ...SUBS].map((m) => [m, SUBS.filter((c) => up[c] === m)]));
    const desc = (m) => KIDS[m].flatMap((c) => [c, ...desc(c)]);
    const chain = (m) => (m === IP ? [] : [...chain(up[m]), up[m]]);

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
      const colN = Object.fromEntries(ids.map((id) => [id, cols[depth[id]].length]));
      return { init, depth, row, main, colN, ncols: cols.length, rmin: Math.min(...rows), rmax: Math.max(...rows), order: ids.slice().sort((a, b) => depth[a] - depth[b] || row[a] - row[b]) };
    }
    const G = Object.fromEntries(Object.keys(M).map((m) => [m, graph(m)]));

    // ---- text: drawn at screen size and scaled by the browser text size, in the page's light face
    const wcache = new Map();
    const font = (px, wt = 300) => `${wt} ${px}px Inter, system-ui, sans-serif`;
    function textW(s, px, wt = 300) { const k = `${wt}|${px}|${s}`; if (!wcache.has(k)) { cx.font = font(px, wt); cx.letterSpacing = "0.6px"; wcache.set(k, cx.measureText(s).width); cx.letterSpacing = "0px"; } return wcache.get(k); }
    const PX = { main: () => 12.5 * FS, name: () => 12 * FS, sub: () => 10 * FS, row: () => 10.5 * FS, dag: () => 10 * FS };
    const subLine = (m) => { const n = M[m].agents.length; return `${M[m].states.length} states · ${n} task${n === 1 ? "" : "s"}${seeded.has(m) ? " (seeded)" : ""}`; };

    // ---- the ledger, in screen pixels. in-progress runs fixed across the top as the template; every other machine is a row under
    // it, its states in one line from first (left) to last (right) across the lane. Rows run newest activity first in one
    // sequence and scroll beneath it, PAGE loaded at a time; a row with a task stuck over 2 h is marked in its place.
    let L = null, W = 0, H = 0, DPR = 1, CW = 0, CH = 0, NX = 52;
    const view = { k: 1, x: 0, y: 0 }, STUCK = 7200, IDLE = 3600, PAGE = 20;
    const key = (m, s) => `${m}:${s}`, node = (m, s) => L.nodes.get(key(m, s));
    function addNode(m, s, x, row) { const nd = { key: key(m, s), m, s, x, y: 0, oy: 0, row, final: isFinal(m, s), initial: initOf(m) === s, label: stName(m, s), r: 4 }; L.nodes.set(nd.key, nd); return nd; }
    const lastOf = (m) => Math.max(0, ...M[m].agents.map((a) => a.active));
    const stuckOf = (m) => M[m].agents.filter((a) => !isFinal(m, a.state) && simT - a.active > STUCK);
    // a row stands for its machine and every machine nested under it: it is stuck, and as recent, as the most stuck and newest of them
    const stuckIn = (m) => stuckOf(m).length > 0 || desc(m).some((d) => stuckOf(d).length > 0);
    const lastIn = (m) => Math.max(lastOf(m), ...desc(m).map(lastOf));
    const rankRows = () => [...L.rows.keys()].sort((a, b) => lastIn(b) - lastIn(a) || (a < b ? -1 : 1));
    // the machine at the top: in-progress, or the machine drilled into; its rows are the machines entered from it
    let topM = IP;
    const rowAt = (m) => { let x = m; while (x !== IP && up[x] !== topM) x = up[x]; return x === IP ? null : x; };
    let order = [], loaded = PAGE, loadingAt = 0, scroll = 0, goal = 0, selRow = null, pointer = null;
    const srcOf = (m) => { const t = primary[m]; return t && node(t.pm, t.ps); };
    const orbitOf = (n) => { const c = tasksAt(n.m, n.s).length; return c ? slot(n, c - 1).R + dotR() : n.r; };
    const fit = (s, px, w, wt) => { if (textW(s, px, wt) <= w) return s; let t = s; while (t.length > 1 && textW(`${t}…`, px, wt) > w) t = t.slice(0, -1); return `${t}…`; };
    const FOOT = () => 34 * FS;
    // a column of three or more states names them beside their nodes, so the gap after it is widened to hold its longest name;
    // the other gaps share what is left evenly
    // a state is drawn bigger the more tasks sit on it; dots grow with the square root of the text size, so 150% stays on the canvas
    const GS = () => Math.sqrt(FS), rOf = (c, row) => (row ? (8 + 1.2 * Math.sqrt(c)) * Math.min(2, row.k) ** 0.6 : 11 + 2.2 * Math.sqrt(c)) * GS();
    const orbAt = (m, s, row) => { const c = tasksAt(m, s).length, r = rOf(c, row); return c ? slot({ r }, c - 1).R + dotR() : r; };
    function colXs(m, x0, x1, px, orb, row) { const g = G[m], n = g.ncols, cols = []; for (const st of M[m].states) (cols[g.depth[st.id]] ||= []).push(st.id);
      const oc = cols.map((c) => (c ? Math.max(...c.map((id) => orbAt(m, id, row))) : 0)), low = oc.slice(0, n - 1).map((o, i) => o + oc[i + 1] + 10);
      const wide = (c) => Math.max(...c.map((id) => textW(stName(m, id), px)));
      // a fan column's names go beside it, and the column before a fan keeps room for half its name above or below
      const need = cols.map((c, i) => (!c ? 0 : c.length >= 3 ? wide(c) + oc[i] + oc[i + 1] + orb : cols[i + 1]?.length >= 3 ? wide(c) / 2 + oc[i + 1] + orb / 2 : 0)).slice(0, n - 1);
      // plain columns share what the named ones leave, each no closer than its orbits allow; only then does everything shrink to fit
      const nf = need.map((v, i) => i).filter((i) => !need[i]), named = need.reduce((a, v, i) => a + (v ? Math.max(v, low[i]) : 0), 0);
      let u = (x1 - x0 - named) / Math.max(1, nf.length);
      for (let it = 0; it < 4; it++) { const big = nf.filter((i) => low[i] > u); u = (x1 - x0 - named - big.reduce((a, i) => a + low[i], 0)) / Math.max(1, nf.length - big.length); }
      const gap = need.map((v, i) => Math.max(v ? 0 : u, v, low[i])), k = (x1 - x0) / Math.max(1, gap.reduce((a, b) => a + b, 0)), xs = [x0];
      gap.forEach((v) => xs.push(xs.at(-1) + v * k)); return xs; }
    // the template: branch states far enough off the main line that their orbits of tasks never touch, two tiers of names above and below
    function hdrOf(m, hn) { const g = G[m], oMax = Math.max(...hn.map(orbitOf)), oBr = Math.max(...hn.filter((n) => g.colN[n.s] > 1).map(orbitOf), 0), lab = PX.main() * 1.3, room = 3.3 * lab + 6,
        rowGap = Math.max(2 * oBr + 6, Math.min(Math.max(2 * oMax + 10, 40 * FS), Math.max(26 * FS, (H * 0.4 - 2 * room - 2 * oMax) / Math.max(1, g.rmax - g.rmin)))),
        span = g.rmax - g.rmin, base = 10 + 2 * room + 2 * oMax;
      return { oMax, room, rowGap, span, base, h0: base + span * rowGap }; }
    const tmplOf = (m) => M[m].states.map((st) => ({ m, s: st.id, r: rOf(tasksAt(m, st.id).length, null) }));
    const tall = (h0) => h0 + clamp(Math.min(0.5 * h0, H * 0.6 - h0), 0, 0.5 * h0);
    function layout() {
      L = { nodes: new Map(), rows: new Map(), stars: [], list: [], ticks: [] };
      const g = G[topM], metaX = NX + 22, metaW = Math.round(clamp(186 * FS, 170, 290)), x0 = metaX + metaW + 34 * FS, x1 = NX + CW - 34, hx = colXs(topM, x0, x1, PX.main(), 40 * FS, null);
      Object.assign(L, { metaX, metaW, x0, x1 });
      const hn = M[topM].states.map((st) => Object.assign(addNode(topM, st.id, hx[g.depth[st.id]], null), { col: RAMP[Math.round((g.depth[st.id] / (g.ncols - 1)) * (RAMP.length - 1))] }));
      radii();
      // in-progress takes half again its natural height, short of 60% of the view; a machine opened below it takes the same height,
      // so every level's top is one size: its branch rows spread apart, the rest pads it above and below
      const { oMax, room, rowGap, span, base, h0 } = hdrOf(topM, hn), hT = Math.max(h0, topM === IP ? tall(h0) : tall(hdrOf(IP, tmplOf(IP)).h0)),
        gap = span ? Math.min(2 * rowGap, rowGap + ((hT - h0) * 0.6) / span) : rowGap, padT = (hT - base - span * gap) / 2;
      L.yMain = 10 + padT + room + oMax - g.rmin * gap; for (const n of hn) n.y = L.yMain + g.row[n.s] * gap;
      L.hdrB = hT; L.laneTop = L.hdrB + 6;
      // each row is as tall as its meta or its machine (branches, names above and below), whichever is taller
      const rg = 32 * FS, pad = 26 * FS + PX.row() * 1.3, metaH = PX.name() * 1.4 + 2 * PX.sub() * 1.5 + 34 * FS;
      // a machine opened deep down may have only a few rows: they stretch, up to 3.2 times, so the lane is filled rather than left empty
      L.stripT = H - 50 * FS; const hOf = (g2) => Math.max(metaH, 2 * pad + (g2.rmax - g2.rmin) * rg), tot = KIDS[topM].reduce((a, m) => a + hOf(G[m]) + nestBand(m), 0);
      const k = KIDS[topM].length <= PAGE ? clamp(((L.stripT - L.laneTop) * 0.97) / Math.max(1, tot), 1, 3.2) : 1;
      KIDS[topM].forEach((m) => { const g2 = G[m], rx = colXs(m, x0, x1, PX.row(), 24 * FS, { k }), r = { m, cy: null, k };
        r.nodes = g2.order.map((s, j) => Object.assign(addNode(m, s, rx[g2.depth[s]], r), { oy: g2.row[s] * rg * k, col: RAMP[Math.round((j / Math.max(1, g2.order.length - 1)) * (RAMP.length - 1))] }));
        r.h = hOf(g2) * k; r.c = r.h / 2 - ((g2.rmax + g2.rmin) / 2) * rg * k; r.band = nestBand(m); r.h += r.band; L.rows.set(m, r);
        const ds = dagTies(m); ds.forEach((t, k) => L.stars.push({ t, dag: t.dag, child: m, row: r, x: x0 - 18 * FS, dy: (k - (ds.length - 1) / 2) * 12 * FS })); });
      const s0 = node(topM, initOf(topM)); dagTies(topM).forEach((t, k) => L.stars.push({ t, dag: t.dag, child: topM, x: s0.x - orbitOf(s0) - 14, y: s0.y + k * 14 }));
      const rv = revEl.getBoundingClientRect(); L.sx0 = Math.max(x0, rv.right + 24); L.sx1 = x1;
      order = rankRows(); place(performance.now());
    }
    function radii() { for (const n of L.nodes.values()) n.r = rOf(tasksAt(n.m, n.s).length, n.row); }
    const regionOf = () => [L.laneTop, L.stripT];
    const shown = (r) => r.on && r.cy < L.stripT && r.cy + r.h > L.laneTop;
    const reg = (n) => (!n.row ? [0, L.hdrB] : regionOf(n.row));
    function place(now) {
      radii();
      L.list = [];
      // one sequence, newest activity first: a stuck row keeps its place and is marked, so the rows in view are one span of time
      L.nStuck = 0; for (const m of order) { const r = L.rows.get(m); r.stuck = stuckIn(m); if (r.stuck) L.nStuck++; L.list.push(r); }
      const n = Math.min(loaded, L.list.length);
      L.more = L.list.length - n; L.content = L.list.slice(0, n).reduce((a, r) => a + r.h, 0) + (L.more ? FOOT() : 0); L.maxScroll = Math.max(0, L.content - (L.stripT - L.laneTop));
      goal = clamp(goal, 0, L.maxScroll); scroll += (goal - scroll) * 0.3; if (Math.abs(goal - scroll) < 0.5) scroll = goal; scroll = clamp(scroll, 0, L.maxScroll);
      let s = L.laneTop - scroll; L.footY = s; L.list.forEach((r, i) => { r.on = i < n; r.y = s; s += r.h; if (i === n - 1) L.footY = s; });
      // the footer coming into view loads the next page, as the DAG ledger does
      if (L.more && L.footY < L.stripT && !loadingAt) loadingAt = now; if (loadingAt && now - loadingAt > 480) { loaded += PAGE; loadingAt = 0; }
      for (const r of L.rows.values()) { r.cy = r.cy == null || Math.abs(r.cy - r.y) > 1500 ? r.y : lerp(r.cy, r.y, 0.3); if (Math.abs(r.cy - r.y) < 0.3) r.cy = r.y; for (const nd of r.nodes) nd.y = r.cy + r.c + nd.oy; }
      for (const st of L.stars) if (st.row) st.y = st.row.cy + st.row.c + st.dy;
    }
    // bring a row on screen: load the page it is on, scroll it to the middle of the lane and select it
    function reveal(r) { if (!r) return; selRow = r; syncUrl(); const i = L.list.indexOf(r); if (i >= loaded) loaded = (Math.floor(i / PAGE) + 1) * PAGE;
      const off = L.list.slice(0, i).reduce((a, q) => a + q.h, 0); goal = off - (L.stripT - L.laneTop - r.h) / 2; }

    // ---- labels of the template: one that would overprint another takes a second tier on a hairline, else it waits for the tooltip
    const hits = (a, b) => (b.r ? Math.hypot(Math.max(a.x0 - b.x, 0, b.x - a.x1), Math.max(a.y0 - b.y, 0, b.y - a.y1)) < b.r : a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1);
    let labels = [];
    function placeLabels() {
      labels = []; const placed = [], X0 = NX + 4, X1 = NX + CW - 4, Y1 = L.hdrB - 2;
      const b = clockEl.getBoundingClientRect(); if (b.width) placed.push({ x0: b.left - 6, x1: b.right + 6, y0: b.top - 4, y1: b.bottom + 4 });
      placed.push({ x0: L.metaX - 4, x1: L.metaX + L.metaW, y0: 0, y1: L.hdrB });
      for (const n of L.nodes.values()) if (!n.row) placed.push({ x: n.x, y: n.y, r: orbitOf(n) + 2 });
      for (const s of L.stars) if (!s.row) placed.push({ x: s.x, y: s.y, r: 7 });
      const put = (cands, w, h, lab) => { for (const c of cands) { const r = { x0: c.x, y0: c.y, x1: c.x + w, y1: c.y + h };
          if (r.x0 < X0 || r.x1 > X1 || r.y0 < 2 || r.y1 > Y1) continue; const pad = { x0: r.x0 - 8, x1: r.x1 + 8, y0: r.y0 - 1, y1: r.y1 + 1 };
          if (placed.some((q) => hits(pad, q))) continue; placed.push(pad); labels.push({ ...lab, lead: c.lead, x: r.x0, y: r.y0 + h / 2, w, h }); return true; } return false; };
      const sides = (p, rr, w, h, ord) => ord.flatMap((sd) => { const xs = [p.x - w / 2, p.x + rr - w, p.x - rr, p.x - w];
        return sd === "below" ? xs.map((x) => ({ x, y: p.y + rr + 3 })) : sd === "above" ? xs.map((x) => ({ x, y: p.y - rr - 3 - h }))
          : sd === "right" ? [{ x: p.x + rr + 10, y: p.y - h / 2 }] : [{ x: p.x - rr - 10 - w, y: p.y - h / 2 }]; });
      const ordOf = (g, s) => (g.colN[s] >= 3 ? ["right", "left", "above", "below"] : g.row[s] < 0 ? ["above", "right", "left", "below"] : g.row[s] > 0 ? ["below", "right", "left", "above"] : g.depth[s] % 2 ? ["above", "below", "right", "left"] : ["below", "above", "right", "left"]);
      // the main line is named first, so a wide fan of branches beside it never takes the places its names need
      const hg = G[topM], heads = [...L.nodes.values()].filter((n) => !n.row).sort((a, b) => (hg.row[a.s] !== 0) - (hg.row[b.s] !== 0));
      for (const n of heads) { const px = PX.main(), w = textW(n.label, px), h = px * 1.3, p = n, rr = orbitOf(n) + 2;
        const far = (dir, k) => [p.x - w / 2, p.x + rr - w, p.x - rr, p.x - w].map((x) => ({ x, y: dir > 0 ? p.y + rr + 3 + h * k : p.y - rr - 3 - h * (k + 1), lead: { x: p.x, y: p.y + dir * rr } }));
        const o = ordOf(G[topM], n.s), d = o[0] === "above" ? -1 : 1; put([...sides(p, rr, w, h, o), ...[1.1, 2.2].flatMap((k) => [...far(d, k), ...far(-d, k)])], w, h, { node: n, px, a: 1 }); }
      for (const s of L.stars) if (!s.row) { const px = PX.dag(), w = textW(s.dag, px), h = px * 1.3;
        put([{ x: s.x - w / 2, y: s.y - 9 - h }, { x: s.x - w / 2, y: s.y + 9 }, { x: s.x - 9 - w, y: s.y - h / 2 }], w, h, { star: s, px }); }
    }

    // ---- geometry shared by the flow lines, the moving tasks and the trace, so a highlight runs exactly where its line is
    let T = 0, last = performance.now();
    const hotM = () => (hover?.kind === "row" ? hover.o.m : hover?.kind === "tick" ? hover.o.m : hover?.kind === "star" ? hover.o.child : hover?.kind === "node" && hover.o.row ? hover.o.m : null);
    function curve(a, b, bend = 0.12) { const dx = b.x - a.x, dy = b.y - a.y; return { p0: a, p1: b, c: { x: (a.x + b.x) / 2 - dy * bend, y: (a.y + b.y) / 2 + dx * bend } }; }
    // a back edge bows over its line, no further than its row allows
    function edgeCurve(s, q) { if (q.x >= s.x - 1) return curve(s, q, s.row ? 0.04 : 0.08); const len = Math.hypot(q.x - s.x, q.y - s.y) || 1; return curve(s, q, s.row ? Math.min(0.28, (s.row.h * 0.6) / len) : 0.28); }
    // a session entering a machine drops from the state it leaves and arrives at the row's first state from above
    function entryPath(a, b) { const dy = b.y - a.y; return { cubic: true, p0: a, c1: { x: a.x, y: a.y + dy * 0.6 }, c2: { x: b.x - 30, y: b.y - Math.min(40, Math.abs(dy) * 0.3) * Math.sign(dy || 1) }, p1: b }; }
    const at = (e, t) => { if (!e.cubic) { const u = 1 - t; return { x: u * u * e.p0.x + 2 * u * t * e.c.x + t * t * e.p1.x, y: u * u * e.p0.y + 2 * u * t * e.c.y + t * t * e.p1.y }; }
      const u = 1 - t; return { x: u ** 3 * e.p0.x + 3 * u * u * t * e.c1.x + 3 * u * t * t * e.c2.x + t ** 3 * e.p1.x, y: u ** 3 * e.p0.y + 3 * u * u * t * e.c1.y + 3 * u * t * t * e.c2.y + t ** 3 * e.p1.y }; };
    const trim = (e, ra, rb) => { const len = Math.hypot(e.p1.x - e.p0.x, e.p1.y - e.p0.y) || 1; return [Math.min(0.4, ra / len), 1 - Math.min(0.4, rb / len)]; };
    function along(e, t0, t1, n = 20) { cx.beginPath(); for (let i = 0; i <= n; i++) { const p = at(e, t0 + ((t1 - t0) * i) / n); i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y); } cx.stroke(); }
    // the page's flow line: a gradient from one end's colour to the other's, dashed, the dashes streaming the way it runs
    function flow(a, b, alpha, heat, d = [2, 5]) { const g = cx.createLinearGradient(a.x, a.y, b.x, b.y); g.addColorStop(0, rgba(a.col, alpha)); g.addColorStop(1, rgba(b.col, alpha));
      cx.strokeStyle = g; cx.lineWidth = 1.1 + heat * 1.5; cx.setLineDash(d.map((v) => v * 1.2)); cx.lineDashOffset = -T * 12 * 1.2; }
    function arrow(p, q, col, len = 8) { const a = Math.atan2(q.y - p.y, q.x - p.x); cx.fillStyle = col; cx.beginPath(); cx.moveTo(q.x, q.y);
      cx.lineTo(q.x - len * Math.cos(a - 0.4), q.y - len * Math.sin(a - 0.4)); cx.lineTo(q.x - len * Math.cos(a + 0.4), q.y - len * Math.sin(a + 0.4)); cx.fill(); }
    const heat = new Map(), heatOf = (k, now) => Math.max(0, 1 - (now - (heat.get(k) ?? -1e9)) / 2600);
    function clip(y0, y1, fn) { if (y1 <= y0) return; cx.save(); cx.beginPath(); cx.rect(NX, y0, CW, y1 - y0); cx.clip(); try { fn(); } finally { cx.restore(); } }

    // ---- drawing, one machine at a time so each row can be clipped to the band it scrolls in
    function drawEdgesOf(m, now) {
      for (const t of M[m].trans) { const s = node(m, t.source), q = node(m, t.target); if (!s || !q) continue;
        const hot = hover?.kind === "node" && (hover.o === s || hover.o === q), h = heatOf(`${s.key}>${q.key}`, now), e = edgeCurve(s, q), [t0, t1] = trim(e, s.r + 1, q.r + 2);
        flow(s, q, Math.min(1, (hot ? 0.95 : s.row ? 0.36 : 0.4) + h * 0.5), h + (hot ? 0.8 : 0), s.row ? [1.5, 4] : [2, 5]); along(e, t0, t1, 16); cx.setLineDash([]); }
    }
    function drawNodesOf(m) { // the page's state: a coloured rim and centre over a faint wash of its own colour
      for (const n of (m === topM ? [...L.nodes.values()].filter((x) => !x.row) : L.rows.get(m).nodes)) { const hot = hover?.kind === "node" && hover.o === n;
        cx.fillStyle = rgba(n.col, hot ? 0.3 : 0.12); cx.beginPath(); cx.arc(n.x, n.y, n.r, 0, TAU); cx.fill();
        cx.strokeStyle = rgba(n.col, hot ? 1 : 0.85); cx.lineWidth = hot ? 2 : n.row ? 1.2 : 1.6; cx.stroke();
        if (n.final) { cx.strokeStyle = rgba(n.col, 0.45); cx.lineWidth = 1; cx.beginPath(); cx.arc(n.x, n.y, n.r + 2.5, 0, TAU); cx.stroke(); }
        cx.fillStyle = rgba(n.col, 0.9); cx.beginPath(); cx.arc(n.x, n.y, Math.min(n.initial && !n.row ? 4.5 : 3, n.r * 0.4), 0, TAU); cx.fill(); }
    }
    function drawStar(s) { const r = 5.5, hot = hover?.kind === "star" && hover.o === s;
      cx.fillStyle = rgba(DAGC, 0.12); cx.beginPath(); cx.arc(s.x, s.y, r * 2, 0, TAU); cx.fill(); cx.fillStyle = rgba(DAGC, hot ? 1 : 0.9); cx.beginPath();
      for (let i = 0; i < 8; i++) { const rr = i % 2 ? r * 0.3 : r, th = (i * Math.PI) / 4 - Math.PI / 2; cx.lineTo(s.x + rr * Math.cos(th), s.y + rr * Math.sin(th)); } cx.closePath(); cx.fill(); }
    function drawStarLine(s, now) { const tgt = node(s.child, initOf(s.child)), fl = Math.max(0, 1 - (now - s.t.flash) / 1600);
      flow({ x: s.x, y: s.y, col: DAGC }, tgt, 0.4 + fl * 0.55, fl, [1, 4]); const [t0, t1] = trim({ p0: s, p1: tgt }, 7, tgt.r + 2);
      cx.beginPath(); cx.moveTo(lerp(s.x, tgt.x, t0), lerp(s.y, tgt.y, t0)); cx.lineTo(lerp(s.x, tgt.x, t1), lerp(s.y, tgt.y, t1)); cx.stroke(); cx.setLineDash([]); }
    // tasks orbit the state they sit on; a moving task rides its flow line to the next state as a comet
    const dotR = () => 3.2 * GS();
    function slot(n, i) { const sp = 8.5 * GS(), base = n.r + 5 * GS(); let rem = i, R = base;
      for (;;) { const cap = Math.max(6, Math.floor((TAU * R) / sp)); if (rem < cap) return { R, a: (rem / cap) * TAU }; rem -= cap; R += 7 * GS(); } }
    const taskPos = new Map();
    function pulse(x, y, u) { cx.strokeStyle = rgba(ACT, 0.7 * (1 - u)); cx.lineWidth = 1.2; cx.beginPath(); cx.arc(x, y, 3 + 18 * u, 0, TAU); cx.stroke(); }
    function drawTasksOf(m, y0, y1, now) {
      for (const n of (m === topM ? [...L.nodes.values()].filter((x) => !x.row) : L.rows.get(m).nodes))
        tasksAt(n.m, n.s).forEach((ag, i) => { const sl = slot(n, i), th = sl.a + T * 0.06, x = n.x + sl.R * Math.cos(th), y = n.y + sl.R * Math.sin(th);
          if (y > y0 && y < y1) taskPos.set(ag, { x, y }); cx.fillStyle = rgba(TIER[tierOf(ag.model)], 0.9); cx.beginPath(); cx.arc(x, y, dotR(), 0, TAU); cx.fill();
          if (ag.kind === "unattended") { cx.strokeStyle = "rgba(6,10,20,.9)"; cx.lineWidth = 0.8; cx.stroke(); }
          if (now - (ag.landed || -1e9) < 1400) pulse(x, y, (now - ag.landed) / 1400); });
    }
    const moveCurve = (ag) => { const fr = ag.move.star || L.nodes.get(ag.move.from), to = node(ag.m, ag.state); if (!fr || !to) return null;
      return ag.move.star ? curve(fr, to, 0.18) : fr.m === ag.m ? (hasEdge(ag.m, fr.s, to.s) ? edgeCurve(fr, to) : curve(fr, to, 0.28)) : entryPath(fr, to); };
    function drawMoves(now) {
      for (const m of Object.values(M)) for (const ag of m.agents) if (ag.move) { const e = moveCurve(ag); if (!e) { ag.move = null; continue; }
        const u = clamp((now - ag.move.t0) / 1400, 0, 1), v = easeO(u), p = at(e, v), to = node(ag.m, ag.state);
        if (!to.row || shown(to.row)) { cx.strokeStyle = rgba(ACT, 0.55); cx.lineWidth = 1.6; along(e, Math.max(0, v - 0.14), v, 8);
          cx.fillStyle = ACT; cx.beginPath(); cx.arc(p.x, p.y, dotR() * 1.5, 0, TAU); cx.fill(); if (p.y < L.stripT) taskPos.set(ag, p); }
        if (u >= 1) { ag.move = null; ag.landed = now; } }
    }
    // the template's own name, the spine under it, and a faint guide down the lane from each state some row is entered from
    function drawHeader(now) {
      const px = PX.name(), sp = PX.sub(), mx = L.metaX, nT = M[topM].agents.length, dy = topM === IP ? 0 : sp * 1.4;
      // drilled in: the machines above this one, each a way back up, and where this one is entered from
      L.crumbs = [];
      if (topM !== IP) { let cs = chain(topM), cut = false; const sep = " › ", wOf = (xs) => textW(`↑ ${cut ? `…${sep}` : ""}${xs.join(sep)}`, sp);
        while (cs.length > 1 && wOf(cs) > L.metaW) { cs = cs.slice(1); cut = true; }
        let x = mx; const y = 8 + sp * 0.6, put = (str, col) => { text(str, x, y, sp, col); const w = textW(str, sp); x += w; return w; };
        put("↑ ", rgba(SUB, 0.6)); if (cut) { put("…", rgba(SUB, 0.6)); put(sep, rgba(SUB, 0.45)); }
        cs.forEach((m, i) => { const hot = hover?.kind === "crumb" && hover.o.m === m, x0 = x, w = put(fit(m, sp, Math.max(24, mx + L.metaW - x)), rgba(PLANET, hot ? 1 : 0.72));
          L.crumbs.push({ m, x0, x1: x0 + w, y0: y - sp * 0.8, y1: y + sp * 0.8 }); if (i < cs.length - 1) put(sep, rgba(SUB, 0.45)); }); }
      text(fit(topM, px * 1.08, L.metaW, 400), mx, 20 + px * 0.5 + dy, px * 1.08, rgba(INK, 0.9), "left", 400);
      text(fit(`${topM === IP ? "template" : "machine"} · ${M[topM].states.length} states · ${nT} tasks`, sp, L.metaW), mx, 22 + px * 1.3 + sp * 0.6 + dy, sp, rgba(SUB, 0.7));
      const tr = topM !== IP && primary[topM];
      if (tr) { const src = M[tr.pm] && G[tr.pm] ? RAMP[Math.round((G[tr.pm].depth[tr.ps] / Math.max(1, G[tr.pm].ncols - 1)) * (RAMP.length - 1))] : PLANET, ly = 22 + px * 1.3 + sp * 2.1 + dy;
        cx.fillStyle = rgba(src, 0.95); cx.beginPath(); cx.arc(mx + 3, ly, 2.6, 0, TAU); cx.fill();
        text(fit(`from ${stName(tr.pm, tr.ps)} · ${tr.kind === "declared" ? "declared" : `×${tr.count}`}`, sp, L.metaW - 11), mx + 11, ly, sp, rgba(INK, 0.62)); }
      text(fit(`${L.rows.size} machine${L.rows.size === 1 ? "" : "s"}${L.nStuck ? ` · ${L.nStuck} stuck` : " · newest first"}`, sp, L.metaW), mx, L.hdrB - sp, sp, rgba(SUB, 0.6));
      cx.fillStyle = rgba(SUB, 0.16); cx.fillRect(mx - 10, L.hdrB, L.x1 + 22 - mx, 1);
      const cols = new Map(); for (const r of L.rows.values()) { const t = primary[r.m]; if (t && t.pm === topM) cols.set(t.ps, node(topM, t.ps)); }
      for (const n of cols.values()) { const hot = hover?.kind === "node" && hover.o === n;
        cx.fillStyle = rgba(n.col, 0.9); cx.beginPath(); cx.arc(n.x, L.hdrB + 0.5, 2.2, 0, TAU); cx.fill();
        clip(L.laneTop, L.stripT, () => { cx.strokeStyle = rgba(n.col, hot ? 0.35 : 0.1); cx.lineWidth = 1; cx.setLineDash([2, 5]); cx.beginPath(); cx.moveTo(n.x, L.hdrB + 3); cx.lineTo(n.x, L.stripT); cx.stroke(); }); }
      clip(0, L.hdrB, () => { drawEdgesOf(topM, now); drawNodesOf(topM); for (const s of L.stars) if (!s.row) { drawStarLine(s, now); drawStar(s); } drawTasksOf(topM, 0, L.hdrB, now); });
    }
    function drawRow(r, now) {
      const ga = Math.abs(r.cy - r.y) > 3 ? 0.3 : 1; cx.globalAlpha = ga;
      const hot = hotM() === r.m || selRow === r, t = primary[r.m], src = srcOf(r.m), y = r.cy, mx = L.metaX, [y0, y1] = regionOf(r);
      const fl = Math.max(0, 1 - (now - (r.flash ?? -1e9)) / 1800); // the row just stepped out of glows for a moment
      if (hot || fl) { cx.fillStyle = rgba(PLANET, Math.max(hot ? (selRow === r ? 0.09 : 0.055) : 0, 0.16 * fl)); cx.fillRect(mx - 10, y, L.x1 + 20 - mx, r.h); }
      cx.fillStyle = rgba(SUB, 0.09); cx.fillRect(mx - 10, y + r.h - 1, L.x1 + 20 - mx, 1);
      if (r.stuck) { cx.fillStyle = rgba(OFF, 0.85); cx.fillRect(mx - 10, y + 6, 2, r.h - 12); }
      // the notch under the column of the template state this machine is entered from: filled when declared, hollow when observed
      if (t && t.pm === topM && src) { cx.fillStyle = rgba(src.col, 0.95); cx.strokeStyle = rgba(src.col, 0.95); cx.lineWidth = 1.2; cx.beginPath(); cx.moveTo(src.x - 4.5, y + 1.5); cx.lineTo(src.x + 4.5, y + 1.5); cx.lineTo(src.x, y + 8); cx.closePath(); t.kind === "declared" ? cx.fill() : cx.stroke(); }
      // meta: its name, where it is entered from, and what its tasks are doing
      const px = PX.name(), sp = PX.sub(), ag = M[r.m].agents, idle = simT - lastIn(r.m) > IDLE, ty = y + r.h / 2 - (px * 1.4 + 2 * sp * 1.5) / 2, st = stuckOf(r.m);
      r.nameAt = { x: mx, y: ty + px * 0.7 };
      // every row opens: a click anywhere on it zooms through to that machine; one with machines entered from it says how many
      const nk = KIDS[r.m].length; let cw = 0;
      { const ct = nk && NESTV === "badge" ? `${nk} nested ›` : "›"; cw = textW(ct, sp) + 8; text(ct, mx + L.metaW, ty + px * 0.7, sp, rgba(PLANET, hot ? 1 : 0.7), "right"); }
      text(fit(r.m, px, L.metaW - cw, 400), mx, ty + px * 0.7, px, rgba(INK, hot ? 0.97 : idle ? 0.55 : 0.85), "left", 400);
      let l2 = "no tie this hour", c2 = rgba(SUB, 0.5), dot = null;
      if (t) { dot = src?.col; l2 = `${t.pm === topM ? "from" : "on"} ${t.pm === topM ? stName(t.pm, t.ps) : `${t.pm} › ${stName(t.pm, t.ps)}`} · ${t.kind === "declared" ? "declared" : `×${t.count}`}`; c2 = rgba(INK, 0.62); }
      else if (dagTies(r.m).length) { l2 = `✦ ${dagTies(r.m).map((d) => d.dag).join(", ")}`; c2 = rgba(DAGC, 0.75); }
      if (dot) { cx.fillStyle = rgba(dot, 0.95); cx.beginPath(); cx.arc(mx + 3, ty + px * 1.4 + sp * 0.75, 2.6, 0, TAU); cx.fill(); }
      text(fit(l2, sp, L.metaW - (dot ? 11 : 0)), mx + (dot ? 11 : 0), ty + px * 1.4 + sp * 0.75, sp, c2);
      const age = (s) => (s >= 3600 ? `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}` : `${Math.max(1, Math.round(s / 60))}m`);
      const ns = st.length ? [] : desc(r.m).flatMap((d) => stuckOf(d).map((a) => ({ a, d }))).sort((p, q) => p.a.active - q.a.active);
      const l3 = st.length ? `stuck ${age(simT - Math.min(...st.map((a) => a.active)))} in ${stName(r.m, st[0].state)}` : ns.length ? `nested stuck ${age(simT - ns[0].a.active)} in ${ns[0].d}`
        : !ag.length ? (desc(r.m).some((d) => M[d].agents.length) ? `${desc(r.m).reduce((n, d) => n + M[d].agents.length, 0)} tasks nested · last ${hhmm(lastIn(r.m))}` : "no sessions this hour")
        : `${ag.length} task${ag.length === 1 ? "" : "s"} · ${idle ? `idle ${age(simT - lastIn(r.m))}` : `last ${hhmm(lastIn(r.m))}`}`;
      text(fit(l3 + (seeded.has(r.m) ? " · seeded" : ""), sp, L.metaW), mx, ty + px * 1.4 + sp * 2.25, sp, st.length || ns.length ? rgba(OFF, 0.9) : rgba(SUB, idle ? 0.5 : 0.7));
      for (const s of L.stars) if (s.row === r) { drawStarLine(s, now); drawStar(s); }
      cx.globalAlpha = ga * (idle && !hot ? 0.75 : 1); drawEdgesOf(r.m, now); drawNodesOf(r.m); cx.globalAlpha = ga; drawTasksOf(r.m, y0, y1, now); drawNest(r, hot); rowLabels(r, hot); cx.globalAlpha = 1;
    }
    // a row with machines entered from it gains a band under its line to draw them in (none for the badge)
    function nestBand(m) {
      if (NESTV === "badge" || !KIDS[m].length) return 0;
      const sp = PX.sub(), g = GS();
      if (NESTV === "mini") return sp * 1.4 + 14 * g;
      if (NESTV === "tray") return sp * 1.6 + 22 * g;
      if (NESTV === "chain") { const cols = chainCols(m); return Math.max(...[...cols].map(([dc, es]) => new Set(es.map((e) => e.s)).size * 5 + Math.max(...es.map((e) => chainH(e.c))) + (chainRoom(m, cols, dc).two ? sp * 1.3 : 0))) + 8; }
      return sp * 1.4 + Math.max(...KIDS[m].map((c) => G[c].rmax - G[c].rmin + 1)) * 5 * g + 10;
    }
    // chain: the machines entered from a row's states, by the column of the state, top state first; and the height of one machine's block
    const chainCols = (m) => { const cols = new Map(); for (const c of KIDS[m]) { const ps = primary[c]?.ps; if (ps == null || !(ps in G[m].depth)) continue; const d = G[m].depth[ps]; (cols.get(d) || cols.set(d, []).get(d)).push({ s: ps, c }); }
      for (const es of cols.values()) es.sort((a, b) => G[m].row[a.s] - G[m].row[b.s] || (a.c < b.c ? -1 : 1)); return cols; };
    const chainH = (c) => Math.min(4, 1 + desc(c).length) * 8 * GS() + PX.sub() * 1.4 + 6;
    // a column's room, from its first state to the next column's, the width of each block, and whether its names alternate between two baselines to fit
    const chainRoom = (m, cols, dc) => { const es = cols.get(dc), nx = [...cols.keys()].sort((a, b) => a - b).find((x) => x > dc), n0 = node(m, es[0].s);
      if (!n0) return { lim: L.x1 + 22, bw: Infinity, two: false };
      const lim = (nx === undefined ? L.x1 + 22 : node(m, cols.get(nx)[0].s).x) - 14, bw = (lim - n0.x + 4) / es.length;
      return { lim, bw, two: es.length > 1 && es.some((e) => textW(e.c, PX.sub()) > bw - 12) }; };
    // review options (&nest=): under each state of a row that machines are entered from, those machines drawn small, each kept to the room before the next such state
    function drawNest(r, hot) {
      r.nestBoxes = [];
      if (NESTV === "badge") return;
      const sp = PX.sub(), g = GS(), al = hot ? 0.95 : 0.72, by = new Map(), bot = r.cy + r.h - 4 * FS, nameY = bot - sp * 0.6;
      for (const c of KIDS[r.m]) { const s = primary[c]?.ps; if (s && node(r.m, s)) (by.get(s) || by.set(s, []).get(s)).push(c); }
      const xs = [...by.keys()].map((s) => node(r.m, s).x).sort((a, b) => a - b);
      const dotCol = (m, q) => { const o = G[m].order; return RAMP[Math.round((o.indexOf(q) / Math.max(1, o.length - 1)) * (RAMP.length - 1))]; };
      const kidsAt = (m, q) => KIDS[m].filter((k) => primary[k]?.ps === q);
      const line = (m, x, y, dx, rr, a) => { const o = G[m].order; cx.strokeStyle = rgba(SUB, 0.35 * a); cx.lineWidth = 1; cx.beginPath(); cx.moveTo(x, y); cx.lineTo(x + (o.length - 1) * dx, y); cx.stroke();
        o.forEach((q, j) => { cx.fillStyle = rgba(dotCol(m, q), a); cx.beginPath(); cx.arc(x + j * dx, y, rr, 0, TAU); cx.fill(); }); };
      // a state a further machine is entered from: a dashed ring, so the nesting shows where it goes on
      const halo = (x, y, rr) => { cx.strokeStyle = rgba(PLANET, al); cx.lineWidth = 1; cx.setLineDash([1.5, 2]); cx.beginPath(); cx.arc(x, y, rr + 2.4 * g, 0, TAU); cx.stroke(); cx.setLineDash([]); };
      if (NESTV === "chain") { // a block per machine in the band under the row: its line, each deeper machine on its own line hung from the state it is entered from, then its name
        const cols = chainCols(r.m), ds = [...cols.keys()].sort((a, b) => a - b), step = 8 * g, rr = 2.4 * g;
        const ext = (m, f) => Math.max(G[m].order.length - 1, ...KIDS[m].map((k) => G[m].order.indexOf(primary[k].ps) + f * ext(k, f)));
        for (const dc of ds) {
          // a column's blocks sit side by side, top state's first; with several states in the column each runs its own stem out of its left, the top state's outermost and lowest, so no two stems cross
          const es = cols.get(dc), sts = [...new Set(es.map((e) => e.s))], K = sts.length, n0 = node(r.m, sts[0]), { lim, bw, two } = chainRoom(r.m, cols, dc);
          const oM = Math.max(...sts.map((q) => orbitOf(node(r.m, q)))), bt = r.cy + r.h - r.band + 4 + K * 5, Lm = Math.max(...es.map((e) => Math.min(4, 1 + desc(e.c).length))), xb = (i) => n0.x - 2 + i * bw, xv = (k) => n0.x - oM - 6 - (K - 1 - k) * 7;
          cx.save(); cx.beginPath(); cx.rect(xv(0) - 4, r.cy, lim - xv(0) + 4, r.h); cx.clip();
          sts.forEach((q, k) => { const n = node(r.m, q), o = orbitOf(n), hy = bt - 2 - k * 5, mine = es.map((e, i) => (e.s === q ? i : -1)).filter((i) => i >= 0);
            cx.strokeStyle = rgba(n.col, al * 0.7); cx.lineWidth = 1; cx.setLineDash(K === 1 ? [2, 3] : []); cx.beginPath();
            if (K === 1) { cx.moveTo(n.x, n.y + o + 1); cx.lineTo(n.x, hy); } else { cx.moveTo(n.x - o - 1, n.y); cx.lineTo(xv(k), n.y); cx.lineTo(xv(k), hy); }
            cx.lineTo(xb(mine.at(-1)) + 2, hy); for (const i of mine) { cx.moveTo(xb(i) + 2, hy); cx.lineTo(xb(i) + 2, bt + step - rr - 1); } cx.stroke(); cx.setLineDash([]); });
          es.forEach((e, i) => { const n = node(r.m, e.s), c = e.c, x0 = xb(i) + 2, w = bw - 12, d = desc(c).length, Lv = Math.min(4, 1 + d), y = bt;
            const dx0 = Math.min(12 * g, (w - 4) / Math.max(1, ext(c, 0.85)));
            let at = 0; const rec = (m, x, dx, q, a) => { const yy = y + ++at * step; line(m, x, yy, dx, q, a);
              for (const kk of KIDS[m]) { if (at >= Lv) return; const xi = x + G[m].order.indexOf(primary[kk].ps) * dx, yq = y + (at + 1) * step;
                cx.strokeStyle = rgba(PLANET, a * 0.6); cx.lineWidth = 1; cx.setLineDash([1.5, 2]); cx.beginPath(); cx.moveTo(xi, yy + q); cx.lineTo(xi, yq - q * 0.85); cx.stroke(); cx.setLineDash([]);
                rec(kk, xi, dx * 0.85, q * 0.85, a * 0.8); } };
            rec(c, x0, dx0, rr, al);
            // names that would not fit their block alternate between two baselines, each running on under its neighbour's
            const ny = y + Lm * step + sp * (two && i % 2 ? 2.25 : 0.95), nw = two ? Math.min(2 * bw, lim - x0) - 12 : w, tail = d > Lv - 1 ? ` +${d - Lv + 1} deeper` : "", lab = fit(c, sp, Math.max(12, nw - textW(tail, sp))), lw = textW(lab, sp);
            text(lab, x0 - 2, ny, sp, rgba(PLANET, al)); if (tail) text(tail, x0 - 2 + lw, ny, sp, rgba(SUB, 0.75)); });
          cx.restore(); r.nestBoxes.push({ x0: xv(0) - 2, x1: lim, y0: bt - K * 5 - 2, y1: r.cy + r.h }); }
        return; }
      for (const [s, ks] of by) {
        const n = node(r.m, s), lim = Math.min(xs.find((x) => x > n.x + 1) ?? Infinity, L.x1 + 22) - 14, top = n.y + orbitOf(n) + 2;
        const two = ks.slice(0, 2), more = ks.length - two.length, mw = more ? textW(`+${more}`, sp) + 8 : 0, slot = Math.min(170 * FS, (lim - n.x - mw) / two.length);
        two.forEach((c, i) => { const x0 = n.x + i * slot; cx.save(); cx.beginPath(); cx.rect(x0 - 8, r.cy, slot, r.h); cx.clip(); kid(c, n, x0, slot - 10, top); cx.restore();
          r.nestBoxes.push({ x0: x0 - 6, x1: x0 + slot - 8, y0: top, y1: bot }); });
        if (more) text(`+${more}`, n.x + two.length * slot, nameY, sp, rgba(SUB, 0.7));
      }
      // one machine entered from state n, kept inside `w` from x0
      function kid(c, n, x0, w, top) {
        const o = G[c].order, N = o.length, d = desc(c).length;
        const stem = (x, y) => { cx.strokeStyle = rgba(n.col, al * 0.7); cx.lineWidth = 1.1; cx.setLineDash([2, 3]); cx.beginPath(); cx.moveTo(n.x, top); x === n.x ? cx.lineTo(x, y) : cx.quadraticCurveTo(n.x, y, x, y); cx.stroke(); cx.setLineDash([]); };
        const label = (x, y, room) => { const tail = d ? (textW(`${c} +${d} deeper`, sp) <= room ? ` +${d} deeper` : ` +${d}`) : "", lab = fit(c, sp, Math.max(12, room - textW(tail, sp))), lw = textW(lab, sp);
          text(lab, x, y, sp, rgba(PLANET, al)); if (tail) text(tail, x + lw, y, sp, rgba(SUB, 0.75)); };
        if (NESTV === "mini") { // a line of its own states, the first under the state it is entered from, its name below
          const y = nameY - sp * 1.25, dx = Math.min(9 * g, (w - 4) / Math.max(1, N - 1)), rr = 2.2 * g;
          stem(x0, y - rr - 1); line(c, x0, y, dx, rr, al); o.forEach((q, j) => kidsAt(c, q).length && halo(x0 + j * dx, y, rr)); label(x0 - 2, nameY, w); return; }
        if (NESTV === "tray") { // a small card under the state it is entered from, its states and name inside; a sheet behind it for each level further down
          const dx = Math.min(9 * g, (w - 20) / Math.max(1, N - 1)), cw = Math.min(w - 6, Math.max((N - 1) * dx, textW(c, sp) + (d ? textW(` +${d}`, sp) : 0)) + 12), y0 = top + 3, ch = bot - y0, sheets = Math.min(2, d ? 1 + (d > 1) : 0);
          for (let k = sheets; k >= 1; k--) { cx.fillStyle = "rgba(10,16,30,.96)"; cx.strokeStyle = rgba(PLANET, 0.22 * al); cx.lineWidth = 1; cx.beginPath(); cx.roundRect(x0 - 6 + 3 * k, y0 - 2 * k, cw, ch, 4); cx.fill(); cx.stroke(); }
          cx.fillStyle = "rgba(14,21,38,.98)"; cx.strokeStyle = rgba(PLANET, 0.45 * al); cx.beginPath(); cx.roundRect(x0 - 6, y0, cw, ch, 4); cx.fill(); cx.stroke();
          stem(x0, y0); const y = y0 + ch * 0.3; line(c, x0, y, dx, 2 * g, al); o.forEach((q, j) => kidsAt(c, q).length && halo(x0 + j * dx, y, 2 * g));
          const ny = y0 + ch * 0.72, tail = d ? ` +${d}` : "", lab = fit(c, sp * 0.95, cw - 10 - textW(tail, sp * 0.95)); text(lab, x0 - 1, ny, sp * 0.95, rgba(PLANET, al)); if (tail) text(tail, x0 - 1 + textW(lab, sp * 0.95), ny, sp * 0.95, rgba(SUB, 0.75)); return; }
        // ghost: its own shape, small: states placed by their depth and row as the page lays a machine out, its transitions faint, its name below
        const gg = G[c], dx = Math.min(10 * g, (w - 4) / Math.max(1, gg.ncols - 1)), span = Math.max(1, gg.rmax - gg.rmin), dy = Math.min(5 * g, (nameY - sp * 0.8 - top - 4) / (span + 1)), rr = 2 * g;
        const mid = (top + 3 + nameY - sp * 0.8) / 2, P2 = (q) => ({ x: x0 + gg.depth[q] * dx, y: mid + (gg.row[q] - (gg.rmax + gg.rmin) / 2) * dy });
        cx.strokeStyle = rgba(SUB, 0.3 * al); cx.lineWidth = 0.9; for (const t of M[c].trans) { const a = P2(t.source), b = P2(t.target); cx.beginPath(); cx.moveTo(a.x, a.y); cx.lineTo(b.x, b.y); cx.stroke(); }
        const p0 = P2(gg.init); stem(p0.x, p0.y - rr - 1);
        for (const q of o) { const p = P2(q); cx.fillStyle = rgba(dotCol(c, q), al); cx.beginPath(); cx.arc(p.x, p.y, rr, 0, TAU); cx.fill(); if (kidsAt(c, q).length) halo(p.x, p.y, rr); }
        label(x0 - 2, nameY, w);
      }
    }
    // a row's state names alternate below and above its line; a name that would touch another, or leave the row, waits for the tooltip
    function rowLabels(r, hot) { const placed = [...(r.nestBoxes || []), ...r.nodes.map((n) => ({ x: n.x, y: n.y, r: orbitOf(n) + 1 })), ...L.stars.filter((s) => s.row === r).map((s) => ({ x: s.x, y: s.y, r: 11 }))], px = PX.row(), h = px * 1.3, g2 = G[r.m];
      for (const n of r.nodes) { n.lab = null; const w = textW(n.label, px), o = orbitOf(n) + 1, up = n.oy < 0 || (n.oy === 0 && g2.depth[n.s] % 2 === 1), xx = clamp(n.x - w / 2, L.x0 - 26 * FS, L.x1 - w);
        // in a fan of three or more, the states above and below hold those places, so the name goes beside the state
        const side = [{ x: n.x + o + 8, y: n.y - h / 2 }, { x: n.x - o - 8 - w, y: n.y - h / 2 }], vert = (up ? [true, false] : [false, true]).map((u) => ({ x: xx, y: u ? n.y - o - 1.5 - h : n.y + o + 1.5 }));
        for (const c of g2.colN[n.s] >= 3 ? [...side, ...vert] : vert) { const b = { x0: c.x - 6, x1: c.x + w + 6, y0: c.y, y1: c.y + h };
          if (b.y0 < r.cy + 1 || b.y1 > r.cy + r.h - 1 || b.x0 < L.x0 - 30 * FS || b.x1 > L.x1 + 8 || placed.some((q) => hits(b, q))) continue;
          placed.push(b); n.lab = { x: c.x, y: c.y + h / 2, px }; text(n.label, c.x, c.y + h / 2, px, rgba(INK, hot ? 0.85 : 0.5)); break; } } }
    // a row's tie, drawn while the row, its source state or a fresh entry calls for it, along the path its sessions take in
    function drawTies(now) {
      const hm = hotM(), hs = hover?.kind === "node" && !hover.o.row ? hover.o : null;
      for (const r of L.rows.values()) { if (!shown(r)) continue;
        for (const t of TIES.filter((x) => x.child === r.m && x.kind !== "dag")) { const a = node(t.pm, t.ps), b = node(r.m, initOf(r.m)); if (!a || !b || (a.row && !shown(a.row))) continue;
          const fl = Math.max(0, 1 - (now - t.flash) / 1600), on = hm === r.m || selRow === r || (hs && hs.m === t.pm && hs.s === t.ps);
          const al = Math.max(on ? (t === primary[r.m] ? 0.9 : 0.45) : 0, fl * 0.9); if (al < 0.02) continue;
          const e = entryPath(a, b), [t0, t1] = trim(e, a.r + 2, b.r + 3); flow(a, b, al, fl + (on ? 0.5 : 0), t.kind === "observed" ? [1.5, 6] : [2, 5]); along(e, t0, t1, 28); cx.setLineDash([]);
          arrow(at(e, t1 - 0.02), at(e, t1), rgba(b.col, al), 7); } }
    }
    function drawThumb() { L.thumb = null; if (!L.maxScroll) return; const x = L.x1 + 18, y0 = L.laneTop + 4, y1 = L.stripT - 6, th = Math.max(24, ((y1 - y0) * (L.stripT - L.laneTop)) / L.content), ty = y0 + ((y1 - y0 - th) * scroll) / L.maxScroll;
      L.thumb = { x, y0, y1, th, ty }; cx.fillStyle = rgba(SUB, 0.08); cx.fillRect(x - 1, y0, 2, y1 - y0); cx.fillStyle = rgba(SUB, hover?.kind === "thumb" || drag?.thumb ? 0.65 : 0.32); cx.beginPath(); cx.roundRect(x - 2, ty, 4, th, 2); cx.fill(); }
    // the last 24 h of machine entries: a tick per session, in the colour of the state it was entered from (amber for a DAG launch)
    function drawStrip() {
      const { sx0, sx1, stripT } = L, t1 = simT, t0 = t1 - 86400, X = (t) => sx0 + ((t - t0) / 86400) * (sx1 - sx0), by = stripT + 30 * FS, sp = PX.sub();
      const inV = L.list.filter((r) => shown(r)).map((r) => lastIn(r.m)).filter((t) => t > t0);
      if (inV.length) { const a = X(Math.min(...inV)), b = X(Math.max(...inV)); cx.fillStyle = rgba(PLANET, 0.12); cx.fillRect(a - 3, by - 14 * FS, b - a + 6, 14 * FS); cx.fillStyle = rgba(PLANET, 0.5); cx.fillRect(a - 3, by, b - a + 6, 1); }
      cx.fillStyle = rgba(SUB, 0.22); cx.fillRect(sx0, by, sx1 - sx0, 1);
      // an hour label every tick that leaves room for it; a narrow strip or large text labels every second or third
      const every = Math.ceil((textW("00:00", sp * 0.95) + 10) / ((10800 / 86400) * (sx1 - sx0)));
      for (let h = Math.ceil(t0 / 10800) * 10800; h <= t1; h += 10800) { const x = X(h); cx.fillStyle = rgba(SUB, 0.3); cx.fillRect(x, by, 1, 4); if (Math.round(h / 10800) % every === 0 && x - sx0 > 18 && sx1 - x > 18) text(hhmm(h), x, by + 11 * FS, sp * 0.95, rgba(SUB, 0.5), "center"); }
      L.ticks = [];
      for (const d of desc(topM)) { const m = rowAt(d); for (const a of M[d].agents) { const t = start(a); if (t < t0) continue; const x = X(t), hot = hotM() === m || (hover?.kind === "tick" && hover.o.a === a), col = a.task ? srcOf(d)?.col || srcOf(m)?.col || PLANET : DAGC;
        L.ticks.push({ x, m, a }); cx.fillStyle = rgba(col, hot ? 1 : 0.62); cx.fillRect(x - 0.75, by - (hot ? 13 : 8) * FS, 1.5, (hot ? 13 : 8) * FS); } }
      const nL = L.list.filter((r) => r.on).length;
      // the count on the right keeps its room; the strip's name gives way to it on a narrow strip
      const cnt = `${inV.length ? `${hhmm(Math.min(...inV))}–${hhmm(Math.max(...inV))} in view · ` : ""}${nL} of ${L.rows.size} loaded`, room = sx1 - sx0 - textW(cnt, sp) - 14;
      if (room > 40) text(fit("24 h · machine entries", sp, room), sx0, stripT + 8 * FS, sp, rgba(SUB, 0.6));
      text(cnt, sx1, stripT + 8 * FS, sp, rgba(SUB, 0.7), "right");
    }

    // ---- the trace: a task's path, in time order, across every machine it has a session in. Each hop is retraced along the
    // flow line it took, in the colours of its two states, all at once as on the Star Map; a hop the machine has no line
    // for bows off in red and dashed; an entry into a machine drops from the template state to the row's first state.
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
    const segCurve = (s) => (s.kind === "entry" ? entryPath(s.a, s.b) : s.off ? curve(s.a, s.b, s.a.row ? Math.min(0.28, (s.a.row.h * 0.6) / (Math.abs(s.b.x - s.a.x) || 1)) : 0.28) : edgeCurve(s.a, s.b));
    const segReg = (s) => (s.kind === "entry" ? [0, L.stripT] : reg(s.a));
    function badge(p, txt, col) { const w = Math.max(16, textW(txt, 10, 600) + 10), h = 15;
      cx.fillStyle = "rgba(6,10,20,0.92)"; cx.strokeStyle = rgba(col, 0.95); cx.lineWidth = 1.1; cx.beginPath(); cx.roundRect(p.x - w / 2, p.y - h / 2, w, h, h / 2); cx.fill(); cx.stroke();
      cx.font = font(10, 600); cx.fillStyle = "#fef3c7"; cx.textAlign = "center"; cx.textBaseline = "middle"; cx.fillText(txt, p.x, p.y + 0.5); }
    function drawTrace() {
      const src = hover?.kind === "task" ? hover.o : pinned; if (!src) return (trace = null);
      trace = { id: src.task || src.id };
      const ok = (n) => !n.row || shown(n.row), segs = traceSegs(src).filter((s) => ok(s.a) && ok(s.b)), geo = [];
      trace.keys = new Set(segs.flatMap((s) => [s.a.key, s.b.key]));
      for (const s of segs) { const e = segCurve(s), [t0, t1] = trim(e, s.a.r + 2, s.b.r + 4); geo.push({ e, t0, t1, s });
        clip(...segReg(s), () => { const col = s.off ? OFF : null, g = cx.createLinearGradient(s.a.x, s.a.y, s.b.x, s.b.y);
          g.addColorStop(0, rgba(col || s.a.col, 0.95)); g.addColorStop(1, rgba(col || s.b.col, 0.95));
          cx.strokeStyle = g; cx.lineWidth = 2.4; cx.setLineDash(s.off ? [5, 5] : []); along(e, t0, t1, 24); cx.setLineDash([]); arrow(at(e, t1 - 0.02), at(e, t1), rgba(col || s.b.col, 0.95), 8); }); }
      // each state the path visits: its rim firms up, and a row's name and state names come back over the veil
      for (const k of trace.keys) { const nd = L.nodes.get(k); if (!nd) continue; clip(...reg(nd), () => { cx.strokeStyle = rgba(nd.col, 1); cx.lineWidth = 2; cx.beginPath(); cx.arc(nd.x, nd.y, nd.r, 0, TAU); cx.stroke();
        if (nd.lab) text(nd.label, nd.lab.x, nd.lab.y, nd.lab.px, rgba(INK, 0.95)); }); }
      for (const m of new Set([...trace.keys].map((k) => L.nodes.get(k)?.row?.m).filter(Boolean))) { const r = L.rows.get(m); clip(...regionOf(r), () => text(fit(m, PX.name(), L.metaW, 400), r.nameAt.x, r.nameAt.y, PX.name(), rgba(INK, 0.97), "left", 400)); }
      // step numbers at each line's middle, a line taken twice carrying both, slid along it clear of the others
      const byLine = new Map(); geo.forEach((g) => { const k = `${g.s.a.key}>${g.s.b.key}>${g.s.kind}`; if (!byLine.has(k)) byLine.set(k, { g, nums: [] }); byLine.get(k).nums.push(g.s.n); });
      const taken = [];
      for (const { g, nums } of byLine.values()) { const txt = nums.join(" · "), w = Math.max(16, textW(txt, 10, 600) + 10) + 4, h = 19;
        const p = [0.5, 0.38, 0.62, 0.28, 0.72].map((t) => at(g.e, lerp(g.t0, g.t1, t))).find((q) => !taken.some((o) => Math.abs(o.x - q.x) < w && Math.abs(o.y - q.y) < h)) || at(g.e, lerp(g.t0, g.t1, 0.5));
        taken.push({ x: p.x, y: p.y }); clip(...segReg(g.s), () => badge(p, txt, g.s.off ? OFF : ACT)); }
      // the traced task's own dots, ringed
      for (const ag of src.task ? byTask[src.task] || [] : [src]) { const p = taskPos.get(ag); if (!p) continue; cx.strokeStyle = rgba(ACT, 0.95); cx.lineWidth = 1.4; cx.beginPath(); cx.arc(p.x, p.y, 6, 0, TAU); cx.stroke(); }
    }
    function text(s, x, y, px, col, align = "left", wt = 300) { cx.font = font(px, wt); cx.letterSpacing = "0.6px"; cx.fillStyle = col; cx.textAlign = align; cx.textBaseline = "middle"; cx.fillText(s, x, y); cx.letterSpacing = "0px"; }
    function drawLabels() {
      placeLabels(); const veil = pinned ? 0.4 : 1, lit = (n) => trace?.keys?.has(n.key);
      for (const l of labels) {
        if (l.star) { cx.globalAlpha = 0.9 * veil; text(l.star.dag, l.x, l.y, l.px, DAGC); cx.globalAlpha = 1; continue; }
        const n = l.node, hot = (hover?.kind === "node" && hover.o === n) || lit(n); cx.globalAlpha = l.a * (hot ? 1 : veil);
        if (l.lead) { const ty = l.lead.y > l.y ? l.y + l.h / 2 : l.y - l.h / 2; cx.strokeStyle = rgba(INK, 0.22); cx.lineWidth = 1; cx.beginPath(); cx.moveTo(l.lead.x, l.lead.y); cx.lineTo(l.lead.x, ty); cx.stroke(); }
        text(n.label, l.x, l.y, l.px, rgba(INK, hot ? 0.95 : 0.7), "left", kidsAt(n.m, n.s).length ? 400 : 300); cx.globalAlpha = 1; }
    }
    // the page's night sky, with its stars, so the zoom through from the Board is seamless
    function nightSky(now) { mcx.setTransform(DPR, 0, 0, DPR, 0, 0); const g = mcx.createRadialGradient(W * 0.5, H * 0.55, 0, W * 0.5, H * 0.55, Math.max(W, H) * 0.75);
      g.addColorStop(0, "#0e1628"); g.addColorStop(1, "#04060b"); mcx.fillStyle = g; mcx.fillRect(0, 0, W, H);
      for (const s of page.stars) { mcx.fillStyle = `rgba(200,215,240,${0.08 + 0.12 * (0.5 + 0.5 * Math.sin(now * 0.0006 + s.p))})`; mcx.beginPath(); mcx.arc(s.x * W, s.y * H, s.r, 0, TAU); mcx.fill(); } }

    let sky = false, enter = null, hover = null, pinned = null;
    function frame(now) {
      requestAnimationFrame(frame); if (!sky) return;
      const dt = Math.min(0.05, (now - last) / 1000); last = now; T += dt;
      place(now); cx = bcx;
      // rows move under a still pointer as the list scrolls or reorders, so what it is over is asked again each frame
      if (pointer && !drag && !enter) { const h = hit(pointer.x, pointer.y); if (h?.kind !== hover?.kind || h?.o !== hover?.o) setHover(h, pointer.x, pointer.y); }
      taskPos.clear();
      cx.setTransform(1, 0, 0, 1, 0, 0); cx.clearRect(0, 0, buf.width, buf.height); cx.setTransform(DPR, 0, 0, DPR, 0, 0);
      drawHeader(now);
      clip(L.laneTop, L.stripT, () => { const sliding = (r) => Math.abs(r.cy - r.y) > 3; for (const k of [true, false]) for (const r of L.list) if (shown(r) && sliding(r) === k) drawRow(r, now);
        // a machine with nothing entered from it still opens: its own states and tasks at the top, and the lane says so
        if (!L.list.length) text(`nothing is entered from ${topM} · Esc steps back out`, (L.x0 + L.x1) / 2, (L.laneTop + L.stripT) / 2, PX.sub(), rgba(SUB, 0.6), "center");
        if (L.more) text(loadingAt ? `loading ${Math.min(PAGE, L.more)} more…` : `${L.more} more · scroll to load`, (L.x0 + L.x1) / 2, L.footY + FOOT() / 2, PX.sub(), rgba(SUB, 0.7), "center"); });
      clip(0, L.stripT, () => { drawTies(now); drawMoves(now); });
      cx.fillStyle = rgba(SUB, 0.16); cx.fillRect(L.metaX - 10, L.stripT, L.x1 + 20 - L.metaX, 1); drawThumb(); drawStrip();
      // a pinned trace is the focused setting: the rest of the ledger steps back under the page's dark veil
      if (pinned) { cx.fillStyle = "rgba(4,6,11,0.66)"; cx.fillRect(0, 0, W, H); }
      drawTrace(); drawLabels();
      nightSky(now); mcx.setTransform(1, 0, 0, 1, 0, 0);
      if (!enter) mcx.drawImage(buf, 0, 0);
      else { // the page's zoom through: the Board blows up past the clicked point and fades while the ledger grows out of it
        const q = Math.min(1, (now - enter.t0) / 520), e = ease(q), f = { x: enter.f.x * DPR, y: enter.f.y * DPR }, out = enter.dir < 0, sN = out ? 2.2 - 1.2 * e : 0.3 + 0.7 * e, sO = out ? 1 - 0.7 * e : 1 + 2.5 * e;
        mcx.globalAlpha = e; mcx.drawImage(buf, f.x * (1 - sN), f.y * (1 - sN), buf.width * sN, buf.height * sN);
        mcx.globalAlpha = 1 - e; mcx.drawImage(enter.snap, f.x * (1 - sO) + (enter.off ?? NAVL) * DPR * sO, f.y * (1 - sO), enter.snap.width * sO, enter.snap.height * sO); mcx.globalAlpha = 1; if (q >= 1) enter = null; }
      const showTop = scroll > 8; topEl.style.display = showTop ? "block" : "none"; if (showTop) { topEl.style.left = `${(L.x0 + L.x1) / 2}px`; topEl.style.top = `${L.laneTop + 8}px`; }
    }

    // ---- into and out of the ledger: the page's go() still moves between levels; this layer takes over the In Progress one
    const cPage = document.getElementById("c"), SKY = [{ kind: "board" }, { kind: "state", id: "in_progress" }];
    const isSky = (p) => p.length === 2 && p[1].kind === "state" && p[1].id === "in_progress";
    function setSky(on) {
      if (on && !sky) pageLegend = legendEl.innerHTML;
      sky = on; document.body.classList.toggle("mv", on); legendEl.innerHTML = on ? skyLegend : pageLegend;
      if (on) { selRow = null; goal = scroll = 0; resize(); } else { setHover(null); pinned = null; topM = IP; }
      const q = new URLSearchParams(location.search); on ? (q.set("level", "in_progress"), topM !== IP ? q.set("open", topM) : q.delete("open")) : (q.delete("level"), q.delete("focus"), q.delete("pick"), q.delete("open")); history.replaceState(null, "", `?${q}`);
    }
    go = function (next, fx, fy, then) {
      const to = isSky(next);
      if (sky && !to) { // out: the page shrinks whatever its canvas shows, so it is handed the ledger as it stands
        const pc = cPage.getContext("2d"); pc.setTransform(1, 0, 0, 1, 0, 0); pc.drawImage(cv, -NAVL * DPR, 0); setSky(false); return page.go(next, fx == null ? fx : fx - NAVL, fy, then); }
      if (!sky && to) {
        const snap = document.createElement("canvas"); snap.width = cPage.width; snap.height = cPage.height; snap.getContext("2d").drawImage(cPage, 0, 0);
        page.go(next, fx, fy, then); page.trans = null; page.mouse = null; document.getElementById("tip").style.opacity = 0; setSky(true); enter = { snap, f: { x: fx == null ? NAVL + (W - NAVL) / 2 : fx + NAVL, y: fy ?? H / 2 }, t0: performance.now() }; return; }
      return page.go(next, fx, fy, then);
    };
    const leave = (sx = NX + CW / 2, sy = H / 2) => go([{ kind: "board" }], sx, sy);
    // drill: a machine takes the top and the machines entered from it become the rows, zooming through the point it was opened
    // from; stepping out zooms back down onto the row it now sits in, which glows a moment
    function drill(m, f, dir = 1) {
      if (!M[m] || m === topM) return; const prev = topM, snap = document.createElement("canvas"); snap.width = cv.width; snap.height = cv.height; snap.getContext("2d").drawImage(cv, 0, 0);
      topM = m; selRow = null; closePanel(); setHover(null); goal = scroll = 0; loaded = PAGE; loadingAt = 0; layout();
      const r = dir < 0 && L.rows.get(rowAt(prev));
      if (r) { reveal(r); selRow = null; scroll = goal; for (const q of L.rows.values()) q.cy = null; place(performance.now()); r.flash = performance.now(); f = { x: L.metaX + L.metaW / 2, y: clamp(r.cy + r.h / 2, L.laneTop, L.stripT) }; }
      syncUrl(); if (f) enter = { snap, f, t0: performance.now(), off: 0, dir };
    }
    const outOne = (sx = NX + CW / 2, sy = H / 2) => drill(up[topM] ?? IP, { x: sx, y: sy }, -1);
    // a machine anywhere below the top: open the machine it is entered from, then bring its row on screen
    function focusMachine(m) { if (!M[m]) return; if (m === IP) { if (topM !== IP) drill(IP, null, -1); selRow = null; goal = 0; syncUrl(); return; }
      if (up[m] !== topM) drill(up[m], null, up[m] === IP || chain(topM).includes(up[m]) ? -1 : 1); reveal(L.rows.get(m)); }
    // step out the way the page does: close the panel, drop the selection, scroll back to the newest, up a machine, then zoom out to the Board
    const back = (sx, sy) => (panel.classList.contains("open") ? closePanel() : selRow ? ((selRow = null), syncUrl()) : goal > 0 ? (goal = 0) : topM !== IP ? outOne(sx, sy) : leave(sx, sy));

    // ---- input: hover names and traces, click pins a task or selects a row, the wheel scrolls the rows
    function hit(sx, sy) {
      if (!L) return null;
      for (const c of L.crumbs || []) if (sx >= c.x0 - 3 && sx <= c.x1 + 3 && sy >= c.y0 && sy <= c.y1) return { kind: "crumb", o: c };
      if (sy >= L.stripT) { if (sx < L.sx0 - 4 || sx > L.sx1 + 4) return null; let best = null;
        for (const t of L.ticks) { const d = Math.abs(t.x - sx); if (d < 4 && (!best || d < best.d)) best = { d, t }; } return best ? { kind: "tick", o: best.t } : null; }
      if (L.thumb && Math.abs(sx - L.thumb.x) < 8 && sy > L.thumb.y0 && sy < L.thumb.y1) return { kind: "thumb" };
      for (const [ag, p] of taskPos) if (Math.hypot(p.x - sx, p.y - sy) < 11) return { kind: "task", o: ag };
      const inReg = (n) => { const [a, b] = reg(n); return sy >= a && sy <= b && (!n.row || shown(n.row)); };
      for (const s of L.stars) if (inReg(s) && Math.hypot(s.x - sx, s.y - sy) < 15) return { kind: "star", o: s };
      for (const n of L.nodes.values()) if (inReg(n) && Math.hypot(n.x - sx, n.y - sy) < Math.max(n.r + 10, 20)) return { kind: "node", o: n };
      for (const l of labels) if (sx >= l.x && sx <= l.x + l.w && Math.abs(sy - l.y) < l.h / 2) return l.star ? { kind: "star", o: l.star } : { kind: "node", o: l.node };
      if (sy > L.laneTop && sx > L.metaX - 12 && sx < L.x1 + 8) { for (const r of L.list) { if (!shown(r)) continue; const [a, b] = regionOf(); if (sy >= Math.max(a, r.cy) && sy < Math.min(b, r.cy + r.h)) return { kind: "row", o: r }; }
        if (L.more && sy >= Math.max(L.laneTop, L.footY) && sy < L.footY + FOOT()) return { kind: "foot" }; }
      return null;
    }
    const tieText = (t) => (t.kind === "declared" ? `opens from <b>${esc(stName(t.pm, t.ps))}</b> <span class="k">declared${t.when ? `, while ${esc(t.when)}` : ""}</span>`
      : `entered from <b>${esc(stName(t.pm, t.ps))}</b> <span class="k">${t.pm !== topM ? `on ${esc(t.pm)} · ` : ""}observed ×${t.count}</span>`);
    function tipHtml(h) {
      if (h.kind === "task") { const ag = h.o, oth = (byTask[ag.task] || []).filter((b) => b !== ag);
        return `<b>${esc(ag.task || ag.title)}</b> <span class="k">${esc(boardTitle[ag.task] || "")}</span><br>${esc(stName(ag.m, ag.state))} <span class="k">on ${esc(ag.m)} · ${hhmm(ag.active)}</span>` +
          (oth.length ? `<br><span class="k">also on</span> ${oth.map((b) => `${esc(b.m)} › ${esc(stName(b.m, b.state))}`).join(", ")}` : "") + `<div class="k">its path is traced in order · click to pin it</div>`; }
      if (h.kind === "node") { const n = h.o, ks = kidsAt(n.m, n.s), sec = TIES.filter((t) => t.pm === n.m && t.ps === n.s && primary[t.child] !== t && t.kind === "observed"), loops = M[n.m].all.filter((t) => t.source === n.s && t.target === n.s).map((t) => t.event);
        return `<b>${esc(n.label)}</b> <span class="k">${esc(n.m)} · ${tasksAt(n.m, n.s).length} tasks${n.final ? " · final" : ""}</span>` +
          [...ks.map((c) => primary[c]), ...sec].map((t) => `<br>${t.kind === "declared" ? "opens" : "enters"} <b>${esc(t.child)}</b> <span class="k">${t.kind === "declared" ? "declared" : `observed ×${t.count}`}</span>`).join("") +
          (loops.length ? `<div class="k">stays here on ${esc(loops.join(", ").toLowerCase())}</div>` : "") + (!n.row && ks.length ? `<div class="k">click to scroll to the first</div>` : ""); }
      if (h.kind === "row") { const m = h.o.m, p = primary[m], o = others(m), d = dagTies(m), st = stuckOf(m);
        return `<b>${esc(m)}</b> <span class="k">${esc(subLine(m))}</span>` + (p ? `<br>${tieText(p)}` : "") + o.map((t) => `<br>${tieText(t)}`).join("") +
          (d.length ? `<br>launched by <b>${d.map((t) => esc(t.dag)).join(", ")}</b>` : "") + (!p && !d.length ? `<br><span class="k">no tie this hour</span>` : "") +
          (st.length ? `<br><span style="color:${OFF}">${st.length} task${st.length === 1 ? "" : "s"} stuck over 2 h</span>` : "") +
          (KIDS[m].length ? `<br>${KIDS[m].length} nested: ${KIDS[m].map(esc).join(", ")}${desc(m).length > KIDS[m].length ? ` <span class="k">+${desc(m).length - KIDS[m].length} deeper</span>` : ""}` : "") +
          `<div class="k">click to open it · Esc steps back out</div>`; }
      if (h.kind === "crumb") return `back up to <b>${esc(h.o.m)}</b>`;
      if (h.kind === "star") { const t = h.o.t; return `<b>${esc(t.dag)}</b> <span class="k">DAG</span><br>launches ${esc(t.child)}${t.child === topM ? "" : ` <span class="k">· ${t.count} session${t.count === 1 ? "" : "s"} with no task</span>`}`; }
      if (h.kind === "tick") { const { a, m } = h.o; return `<b>${esc(a.task || "unattended run")}</b> entered <b>${esc(a.m)}</b> <span class="k">${a.m !== m ? `in ${esc(m)} · ` : ""}${hhmm(start(a))}</span><div class="k">click to scroll to its row</div>`; }
      if (h.kind === "foot") return `<span class="k">loads the next ${PAGE}</span>`;
      return "";
    }
    function setHover(h, sx, sy) { hover = h; cv.classList.toggle("hot", !!h); const html = h ? tipHtml(h) : ""; if (!html) { tip.style.opacity = 0; return; } if (tip.innerHTML !== html) tip.innerHTML = html; tip.style.opacity = 1;
      const r = tip.getBoundingClientRect(); tip.style.left = `${Math.min(sx + 14, W - r.width - 8)}px`; tip.style.top = `${Math.min(sy + 14, H - r.height - 8)}px`; }
    function openTask(ag) { pinned = ag; const all = byTask[ag.task] || [ag], colOf = (m) => node(m, initOf(m))?.col || RAMP[2];
      panel.innerHTML = `<span class="x">✕</span><h2>${esc(ag.task || ag.title)}</h2><div class="k">${esc(boardTitle[ag.task] || ag.title || "")}</div>
        <table>${all.map((b) => `<tr class="mrow"><td><i style="background:${colOf(b.m)}"></i>${esc(b.m)}</td><td>${esc(stName(b.m, b.state))}</td><td style="text-align:right;color:#6b7a93">${hhmm(b.active)}</td></tr>`).join("")}</table>
        <div class="k" style="margin-top:10px">path · ${traceSegs(ag).length} steps, in order</div><table class="trace">${traceSegs(ag).map((s) => `<tr><td>${s.n}</td><td>${s.kind === "entry" ? `<b>${esc(s.b.m)}</b> <span class="k">entered from ${esc(stName(s.a.m, s.a.s))}</span>` : `${esc(stName(s.a.m, s.a.s))} → ${esc(stName(s.b.m, s.b.s))} <span class="k">${esc(s.b.m)}</span>`}</td><td>${hhmm(s.at)}</td></tr>`).join("")}</table>`;
      panel.classList.add("open"); panel.querySelector(".x").onclick = closePanel; }
    function closePanel() { panel.classList.remove("open"); pinned = null; }
    // a row with machines nested in it opens on a click anywhere on it; any other row is selected, keeping its tie drawn
    const select = (r, e) => drill(r.m, { x: e.clientX, y: e.clientY });
    let drag = null;
    cv.addEventListener("mousemove", (e) => { pointer = { x: e.clientX, y: e.clientY }; if (enter) return;
      if (drag) { const k = L.maxScroll / Math.max(1, L.thumb ? L.thumb.y1 - L.thumb.y0 - L.thumb.th : 1); goal = scroll = clamp(drag.g0 + (e.clientY - drag.y) * k, 0, L.maxScroll); return; }
      setHover(hit(e.clientX, e.clientY), e.clientX, e.clientY); });
    cv.addEventListener("mouseleave", () => { pointer = null; setHover(null); });
    cv.addEventListener("mousedown", (e) => { if (e.button === 0 && hover?.kind === "thumb") { drag = { thumb: true, y: e.clientY, g0: goal }; cv.classList.add("drag"); } });
    addEventListener("mouseup", () => { cv.classList.remove("drag"); setTimeout(() => (drag = null)); });
    cv.addEventListener("click", (e) => { if (drag || enter) return; const h = hit(e.clientX, e.clientY);
      if (!h) return closePanel();
      if (h.kind === "task") return openTask(h.o);
      if (h.kind === "row") return select(h.o, e);
      if (h.kind === "crumb") return drill(h.o.m, { x: e.clientX, y: e.clientY }, -1);
      if (h.kind === "node" && h.o.row) return select(h.o.row, e);
      if (h.kind === "node") { const k = kidsAt(topM, h.o.s).map((m) => L.rows.get(m)).sort((a, b) => order.indexOf(a.m) - order.indexOf(b.m)); return k.length && reveal(k[0]); }
      if (h.kind === "star" && h.o.row) return select(h.o.row, e);
      if (h.kind === "tick") return reveal(L.rows.get(h.o.m));
      if (h.kind === "foot") loaded += PAGE; });
    cv.addEventListener("contextmenu", (e) => { e.preventDefault(); if (!enter) back(e.clientX, e.clientY); });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); if (enter) return; goal = clamp(goal + e.deltaY * (e.deltaMode === 1 ? 18 : 1), 0, L.maxScroll); setHover(hit(e.clientX, e.clientY), e.clientX, e.clientY); }, { passive: false });
    topEl.addEventListener("click", () => (goal = 0));
    addEventListener("keydown", (e) => { if (!sky || e.target.tagName === "INPUT") return; let used = true; const pg = (L.stripT - L.laneTop) * 0.9;
      if (e.key === "PageDown") goal += pg; else if (e.key === "PageUp") goal -= pg; else if (e.key === "Home" || e.key === "0") goal = 0; else if (e.key === "End") goal = 1e9;
      else if (e.key === "ArrowDown") goal += 60 * FS; else if (e.key === "ArrowUp") goal -= 60 * FS; else if (e.key === "Escape" || e.key === "Backspace") back(); else used = false;
      if (used) { goal = clamp(goal, 0, L.maxScroll); e.stopPropagation(); e.preventDefault(); } }, true);
    // navigator rows: a machine row scrolls the ledger to that machine's row (zooming in from the Board first); In progress goes back to the newest
    document.getElementById("layers").addEventListener("click", (e) => { const b = e.target.closest(".node"), t = b?.querySelector(".t")?.textContent?.trim(); if (!b || e.target.classList.contains("chev")) return;
      if (sky && b.classList.contains("here")) { e.stopPropagation(); focusMachine(IP); return; }
      if (!(t && M[t])) return;
      e.stopPropagation(); if (!sky) go(SKY); setTimeout(() => focusMachine(t), sky ? 0 : 540); }, true);

    // ---- the address that reproduces the view, and the review-only text size switch
    function syncUrl() { const q = new URLSearchParams(location.search); selRow ? q.set("focus", selRow.m) : q.delete("focus"); topM !== IP ? q.set("open", topM) : q.delete("open"); q.delete("pick"); history.replaceState(null, "", `?${q}`); }
    function setFS(p) { document.documentElement.style.fontSize = p === 100 ? "" : `${p}%`; const q = new URLSearchParams(location.search); p === 100 ? q.delete("fs") : q.set("fs", p); history.replaceState(null, "", `?${q}`); dispatchEvent(new Event("resize")); }
    function renderRev() { const fs = Math.round(FS * 100); revEl.innerHTML = `review · text ` + [100, 125, 150].map((p) => `<button data-fs="${p}" class="${p === fs ? "on" : ""}">${p}%</button>`).join("") +
        ` · nesting ` + NESTS.map((v) => `<button data-nest="${v}" class="${v === NESTV ? "on" : ""}">${v}</button>`).join("");
      revEl.querySelectorAll("[data-nest]").forEach((b) => (b.onclick = () => { NESTV = b.dataset.nest; const q = new URLSearchParams(location.search); NESTV === "badge" ? q.delete("nest") : q.set("nest", NESTV); history.replaceState(null, "", `?${q}`); renderRev(); dispatchEvent(new Event("resize")); }));
      revEl.querySelectorAll("[data-fs]").forEach((b) => (b.onclick = () => setFS(+b.dataset.fs))); }
    function resize() { DPR = devicePixelRatio || 1; NX = NAVW(); W = innerWidth - RAILW(); H = innerHeight; CW = W - NX; CH = H;
      for (const c of [cv, buf]) { c.width = W * DPR; c.height = H * DPR; } cv.style.width = `${W}px`; cv.style.height = `${H}px`;
      readFS(); wcache.clear(); renderRev(); if (!sky && L) return; const keep = selRow?.m; layout(); if (keep) selRow = L.rows.get(keep); }

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
      const pool = Object.values(M).flatMap((m) => m.agents).filter((a) => !a.move && !isFinal(a.m, a.state) && M[a.m].trans.some((t) => t.source === a.state) && simT - a.active < STUCK);
      const weighted = pool.filter((a) => a.m !== IP || Math.random() < 0.35), ag = pick(weighted.length ? weighted : pool); if (!ag) return;
      const t = pick(M[ag.m].trans.filter((x) => x.source === ag.state)); moveTo(ag, t.target, t.event);
      log(`<b>${esc(ag.task || ag.id.slice(0, 8))}</b> ${esc(t.event.toLowerCase())} <em>${esc(ag.m)}</em>`);
    }
    function retire() { const now = performance.now(); for (const m of Object.values(M)) { const gone = m.agents.filter((a) => a.sim && a.doneAt && now - a.doneAt > 9000 && a !== pinned);
      if (gone.length) { if (primary[m.name]) primary[m.name].flash = now; m.agents = m.agents.filter((a) => !gone.includes(a)); indexTasks(); } } }
    // the order holds still while the pointer is over the rows, a row is selected or a trace is pinned, so nothing moves under the hand
    const frozen = () => (pointer && L && pointer.y > L.laneTop && pointer.y < L.stripT) || pinned || selRow || drag;
    let tick = 0; setInterval(() => { if (document.hidden || !sky) return; simStep(); retire(); if (++tick % 3 === 0 && !frozen()) order = rankRows(); }, 1700);

    // ---- start where the address says: the Board by default, the ledger for &level=in_progress, &focus= or &pick=
    const want = P.get("level") === "in_progress" || P.get("focus") || P.get("pick") || P.get("open");
    if (M[P.get("open")] && P.get("open") !== IP) topM = P.get("open");
    if (want && !isSky(page.stack)) { page.go(SKY); page.trans = null; }
    else if (!want && !P.get("level") && page.stack.length !== 1) { page.go([{ kind: "board" }]); page.trans = null; }
    resize(); renderFeed(); renderClock(); addEventListener("resize", resize); document.fonts?.ready.then(() => { wcache.clear(); resize(); });
    setSky(isSky(page.stack));
    const f0 = P.get("focus"); if (sky && f0 && M[f0] && f0 !== IP) focusMachine(f0);
    if (sky && P.get("pick") === "busy") { const t = Object.entries(byTask).filter(([, v]) => !v.every((a) => seeded.has(a.m) || a.m === IP)).sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1))[0]; if (t) openTask(t[1].find((a) => a.m !== IP) || t[1][0]); }
    requestAnimationFrame(frame);
  }
})();
