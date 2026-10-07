"use strict";
/*
  Design review only: four ways to draw the in-progress machine together with its sub-machines, over the saved
  snapshot in data.js. Off unless the address names a variant; the rest of the mockup is untouched.

    ?mv=sat     linked satellites: each sub-machine a small constellation below the state it is entered from, tethered to it
    ?mv=nest    nested: a state that opens sub-machines holds them in a box hanging from it, statechart style
    ?mv=metro   metro lines: in-progress is the trunk, each sub-machine a branch line off its station
    ?mv=orbit   orbital rings: in-progress states on a ring, each sub-machine an orbit of beads round its state

  Add &fs=125 or &fs=150 for the browser text size, &focus=<machine> to open on one machine's ties, &pick=busy to
  open the panel of the task that sits on the most machines at once. Wheel scrolls a view taller than the window, Ctrl+wheel zooms. Keys: 1-4 switch variant, 0 refits, Escape
  clears. A tie is declared (a state's `flow:`), observed (the state a task held when one of its sessions entered
  the sub-machine, read from the trails) or a DAG launch. A machine's most-used tie is drawn at rest; its other
  observed ties show on hovering the machine or the state. running-skill-evals had no session in the saved
  snapshot, so two are seeded from the live shape (a task drafting a skill asks for an eval run).
*/
(() => {
  const P = new URLSearchParams(location.search);
  if (!P.get("mv")) return;
  try { localStorage.setItem("fv.path", JSON.stringify([{ kind: "board" }, { kind: "state", id: "in_progress" }])); } catch (e) { /* private window */ }
  if (P.get("fs")) document.documentElement.style.fontSize = `${+P.get("fs")}%`;
  addEventListener("load", init);

  function init() {
    const S = window.SNAP, F = S.flows, TAU = Math.PI * 2, TZ = "America/Phoenix", IP = "in-progress", NAVW = 250, RAILW = 250;
    const VARIANTS = {
      sat: ["Linked satellites", "Each sub-machine is its own small constellation below the state it is entered from, tethered to it."],
      nest: ["Nested", "A state that opens sub-machines holds them in a box hanging from it; a sub-machine's own sub-machine nests inside."],
      metro: ["Metro lines", "in-progress is the trunk; each sub-machine branches off at the station it is entered from and hooks back to it."],
      orbit: ["Orbital rings", "in-progress states ring the centre; each sub-machine orbits the state it is entered from. DAG-launched machines orbit their DAG's star below."],
    };
    let MV = VARIANTS[P.get("mv")] ? P.get("mv") : "sat";
    const ACT = "#fbbf24", DAGC = "#fbbf24";
    const MCOL = { [IP]: "#a78bfa", "triaging-cr-reviews": "#f0abfc", "authoring-skills": "#86efac", "running-skill-evals": "#7dd3fc",
      "auditing-infrastructure": "#fcd34d", "investigating-dependency-updates": "#fdba74" };
    const colOf = (m) => MCOL[m] || "#94a3b8";
    const TIER = { deep: "#c4b5fd", standard: "#67e8f9", other: "#fde68a" };
    const tierOf = (m = "") => (/opus|deep/.test(m) ? "deep" : /sonnet|standard/.test(m) ? "standard" : "other");
    const rgba = (h, a) => { const n = parseInt(h.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
    const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const hhmm = (sec) => new Date(sec * 1000).toLocaleTimeString("en-US", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false });
    const easeO = (u) => 1 - Math.pow(1 - u, 3);
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    let FS = 1;
    const readFS = () => (FS = parseFloat(getComputedStyle(document.documentElement).fontSize) / 16 || 1);

    // ---- page chrome: the live page's pinned 250 px navigator, this layer's canvas, tooltip, switcher and feed
    const css = document.createElement("style");
    css.textContent = `
      body.mv #c, body.mv #clock, body.mv #crumbs { display: none; }
      body.mv #nav { width: ${NAVW}px; } body.mv #nav::after { display: none; }
      body.mv #full { opacity: 1; pointer-events: auto; width: ${NAVW}px; padding: 20px 18px; border-right: 1px solid rgba(148,163,184,.10); }
      body.mv #full::before { -webkit-mask-image: none; mask-image: none; background: rgba(8,12,22,.86); }
      #mv { position: fixed; left: 0; top: 0; display: block; cursor: default; } #mv.pan { cursor: grab; } #mv.drag { cursor: grabbing; } #mv.hot { cursor: pointer; }
      #mvtip { position: fixed; z-index: 4; pointer-events: none; padding: .5rem .7rem; border-radius: 8px; font-size: .75rem; line-height: 1.5; max-width: 26rem;
        background: rgba(12,19,34,.94); border: 1px solid rgba(148,163,184,.18); backdrop-filter: blur(6px); opacity: 0; transition: opacity .12s; color: #dbe4f3; }
      #mvtip .k { color: #6b7a93; font-size: .6875rem; } #mvtip b { font-weight: 500; }
      #mvbar { position: fixed; z-index: 4; bottom: 14px; transform: translateX(-50%); display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; align-items: center;
        font-size: .6875rem; width: max-content; max-width: calc(100vw - ${NAVW + RAILW + 40}px); }
      #mvbar button { all: unset; white-space: nowrap; cursor: pointer; padding: .2rem .6rem; border-radius: 5px; border: 1px solid rgba(148,163,184,.25); color: #6b7a93; background: rgba(6,10,20,.85); }
      #mvbar button:hover { color: #dbe4f3; } #mvbar button.on { color: #fbbf24; border-color: #fbbf24; } #mvbar .sep { width: 1px; height: 14px; background: rgba(148,163,184,.25); margin: 0 4px; }
      #mvnote { position: fixed; z-index: 4; top: 14px; transform: translateX(-50%); font-size: .75rem; color: #8b95a8; text-align: center; width: max-content; max-width: calc(100vw - ${NAVW + RAILW + 80}px); pointer-events: none; }
      #mvnote b { color: #dbe4f3; font-weight: 500; } #mvnote span { color: #fbbf24; font-family: "JetBrains Mono", ui-monospace, monospace; font-size: .6875rem; margin-left: .6rem; }
      #mvfeed { font: 10.5px/1.75 "JetBrains Mono", ui-monospace, monospace; flex: 1; min-height: 0; overflow: hidden; }
      #mvfeed div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } #mvfeed b { font-weight: 400; color: #dbe4f3; } #mvfeed em { font-style: normal; opacity: .6; }
      #mvfeed div.new { animation: flash 1.2s; }
      #panel .mrow td:first-child i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; }
    `;
    document.head.append(css);
    document.body.classList.add("mv");
    const cv = document.createElement("canvas"); cv.id = "mv"; document.body.prepend(cv);
    const cx = cv.getContext("2d");
    const tip = Object.assign(document.createElement("div"), { id: "mvtip" }); document.body.append(tip);
    const bar = Object.assign(document.createElement("div"), { id: "mvbar" }); document.body.append(bar);
    const note = Object.assign(document.createElement("div"), { id: "mvnote" }); document.body.append(note);
    const panel = document.getElementById("panel");
    const feedEl = document.getElementById("feed"); feedEl.style.display = "none";
    const feed = Object.assign(document.createElement("div"), { id: "mvfeed" }); feedEl.after(feed);
    const line = (style) => `<i style="background:none;border-radius:0;height:0;width:14px;vertical-align:3px;border-top:${style}"></i>`;
    document.getElementById("legend").innerHTML = `<h3>Legend</h3>
      <span><i style="background:${TIER.deep}"></i>deep</span><span><i style="background:${TIER.standard}"></i>standard</span><span><i style="background:${TIER.other}"></i>other</span><br>
      <span>${line("2px solid #cbd5e1")}declared tie</span> <span>${line("2px dashed #cbd5e1")}observed ×n</span><br>
      <span>${line(`2px dotted ${DAGC}`)}DAG launch</span> <span><i style="background:none;border:1.5px solid #cbd5e1;box-sizing:border-box;box-shadow:0 0 0 2px #0a0e1a,0 0 0 3px #cbd5e1"></i>final state</span><br>
      <span><i style="background:${ACT};box-shadow:0 0 6px ${ACT}"></i>activity now</span>`;

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
    const lineage = (m) => { const out = new Set([m]); let p = primary[m]; while (p) { out.add(p.pm); p = primary[p.pm]; } const down = (x) => { for (const c of SUBS) if (primary[c]?.pm === x && !out.has(c)) { out.add(c); down(c); } }; down(m); return out; };

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
      return { init, depth, row, main, cols, ncols: cols.length, rmin: Math.min(...rows), rmax: Math.max(...rows), mainList: ids.filter((id) => main.has(id)).sort((a, b) => depth[a] - depth[b]) };
    }
    const G = Object.fromEntries(Object.keys(M).map((m) => [m, graph(m)]));
    const stateR = (n, small) => (small ? 4 + 1.5 * Math.sqrt(n) : 7 + 2.1 * Math.sqrt(n));

    // ---- text: drawn at screen size and scaled by the browser text size, so a layout is measured in it
    const wcache = new Map();
    const font = (px, wt = 400) => `${wt} ${px}px Inter, system-ui, sans-serif`;
    function textW(s, px, wt = 400) { const k = `${wt}|${px}|${s}`; if (!wcache.has(k)) { cx.font = font(px, wt); wcache.set(k, cx.measureText(s).width); } return wcache.get(k); }
    const MPX = () => 10.5 * FS, IPX = () => 12 * FS, TPX = (big) => (big ? 13 : 12) * FS;
    const labW = (m, s) => textW(stName(m, s), m === IP ? IPX() : MPX()) + (M[m].agents.some((a) => a.state === s) ? textW(" 00", MPX() * 0.9) : 0);
    const titleW = (m, big) => Math.max(textW(m, TPX(big), 500), textW(subTitle(m), TPX(big) * 0.85));

    // ---- a layout: nodes (states), frames (hulls, boxes, rings, lines), ties drawn, DAG glyphs, machine titles
    let L = null, layoutId = 0, W = 0, H = 0, DPR = 1, CW = 0, CH = 0;
    const key = (m, s) => `${m}:${s}`;
    const newLayout = () => ({ nodes: new Map(), frames: [], ties: [], glyphs: [], titles: [], tracks: [], kind: MV, centre: null });
    function addNode(m, s, x, y, o = {}) { const n = M[m].agents.filter((a) => a.state === s).length;
      const nd = { key: key(m, s), m, s, x, y, r: o.r ?? stateR(n, m !== IP), final: isFinal(m, s), initial: initOf(m) === s, sides: o.sides, phi: o.phi, label: stName(m, s) };
      L.nodes.set(nd.key, nd); return nd; }
    const node = (m, s) => L.nodes.get(key(m, s));
    const glyph = (dag, x, y, child, quiet) => { const g = { dag, x, y, child, quiet }; L.glyphs.push(g); return g; };
    // label sides: a state above its row reads above, below reads below, the row alternates by column so neighbours never share a side
    const sidesFor = (m, s) => { const g = G[m]; if (kidsAt(m, s).length && L.kind !== "orbit") return ["above", "right", "left", "below"];
      return g.row[s] < 0 ? ["above", "left", "right", "below"] : g.row[s] > 0 ? ["below", "right", "left", "above"] : g.depth[s] % 2 ? ["above", "below", "right", "left"] : ["below", "above", "right", "left"]; };
    // a sub-machine drawn small: columns as wide as its labels need when neighbours alternate sides
    function miniGap(m) { let w = 0; for (const st of M[m].states) w = Math.max(w, labW(m, st.id)); return Math.max(44 * FS, w * 0.62 + 14 * FS); }
    function mini(m, sx = 1) { const g = G[m], cg = miniGap(m) * sx, rg = 32 * FS; return { g, cg, rg, w: (g.ncols - 1) * cg, top: g.rmin * rg, bot: g.rmax * rg, at: (s) => ({ x: g.depth[s] * cg, y: g.row[s] * rg }) }; }
    function placeMini(m, ox, oy, mi) { for (const st of M[m].states) { const p = mi.at(st.id); addNode(m, st.id, ox + p.x, oy + p.y, { sides: sidesFor(m, st.id) }); } }
    const PAD = () => 14 * FS, TTL = () => 40 * FS, LAB = () => 20 * FS;
    // rows of boxes, each wanting a centre x: greedy rows by width, then packed left to right near their wants
    function pack(items, gap, margin) {
      items.sort((a, b) => a.want - b.want); let right = margin;
      for (const it of items) { it.x0 = Math.max(it.want - it.w / 2, right); right = it.x0 + it.w + gap; }
      let shift = right - gap - (CW - margin);
      for (let i = items.length - 1; i >= 0 && shift > 0; i--) { const it = items[i], room = i ? it.x0 - (items[i - 1].x0 + items[i - 1].w + gap) : it.x0 - margin; it.x0 -= shift; shift = Math.max(0, shift - room); }
    }
    function shelf(items, y, gap = 34 * FS, margin = 12 * FS) {
      if (!items.length) return y;
      items.sort((a, b) => a.want - b.want); const rows = [[]]; let used = 0;
      for (const it of items) { if (rows.at(-1).length && used + it.w > CW - 2 * margin) { rows.push([]); used = 0; } rows.at(-1).push(it); used += it.w + gap; }
      for (const row of rows) { pack(row, gap, margin); const h = Math.max(...row.map((b) => b.h)); for (const b of row) b.put(b.x0, y); y += h + gap; }
      return y - gap;
    }
    // a sub-machine in a frame of its own: title, then its states; DAGs that launch it stand on its top edge
    function hullItem(m, o = {}) {
      const mi = mini(m), w = Math.max(mi.w + 2 * PAD() + 30 * FS, titleW(m) + 2 * PAD()), h = TTL() + LAB() + (mi.bot - mi.top) + LAB() + PAD();
      return { m, w, h, want: o.want, put(x0, y0) {
        placeMini(m, x0 + PAD() + 15 * FS, y0 + TTL() + LAB() - mi.top, mi);
        L.frames.push({ type: o.type || "hull", m, x: x0, y: y0, w, h, dim: o.dim, kind: o.kind });
        L.titles.push({ m, x: x0 + 12 * FS, y: y0 + 14 * FS, dim: o.dim });
        let gx = x0 + w - 12 * FS; for (const t of dagTies(m)) { gx -= textW(t.dag, 10 * FS) + 12 * FS; glyph(t.dag, gx, y0, m); gx -= 14 * FS; } } };
    }
    // the in-progress trunk across the region, its title above-left and the DAG that launches it before its start
    function trunk(y0, rowGap, mx) {
      const g = G[IP], colW = (CW - 2 * mx) / (g.ncols - 1);
      for (const st of M[IP].states) addNode(IP, st.id, mx + g.depth[st.id] * colW, y0 + g.row[st.id] * rowGap, { sides: sidesFor(IP, st.id) });
      L.titles.push({ m: IP, x: mx - 24 * FS, y: y0 + g.rmin * rowGap - 58 * FS, big: true });
      const s0 = node(IP, initOf(IP)); for (const t of dagTies(IP)) glyph(t.dag, s0.x - 10 * FS, s0.y - 38 * FS, IP);
      return y0 + g.rmax * rowGap;
    }
    const dock = (y) => { if (!dormant.length) return y; L.titles.push({ caption: "no tie in this window", x: 12 * FS, y: y + 6 * FS }); return shelf(dormant.map((c, i) => hullItem(c, { want: (CW * (i + 0.5)) / dormant.length, dim: true, kind: "none" })), y + 22 * FS); };

    function laySat() {
      L = newLayout(); const g = G[IP], rowGap = 52 * FS, gapV = 54 * FS;
      let y = shelf(dagOnly.map((c, i) => hullItem(c, { want: (CW * (i + 1)) / (dagOnly.length + 1), kind: "dag" })), 0);
      const y0 = y + gapV + 60 * FS - g.rmin * rowGap;
      y = trunk(y0, rowGap, 70 * FS) + 40 * FS + gapV;
      for (let d = 1; d <= 3; d++) { const tier = tied.filter((c) => depthOf(c) === d); if (!tier.length) continue;
        y = shelf(tier.map((c) => hullItem(c, { want: node(primary[c].pm, primary[c].ps).x, kind: primary[c].kind })), y) + gapV; }
      dock(y);
      tiesFor(["primary"]);
      return L;
    }

    // nested: a state's box holds the machines it opens; a state inside that holds its own one level deeper
    function nestBox(pm, ps) {
      const secs = kidsAt(pm, ps).map((c) => { const mi = mini(c), x0 = PAD() + 15 * FS, inner = M[c].states.filter((s) => kidsAt(c, s.id).length).map((s) => ({ s: s.id, b: nestBox(c, s.id) }));
        let w = Math.max(x0 + mi.w + 15 * FS + PAD(), titleW(c) + 2 * PAD()), h = TTL() + LAB() + (mi.bot - mi.top) + LAB() + PAD(), ix = 0, ih = 0;
        for (const n of inner) { n.dx = Math.max(ix, x0 + mi.at(n.s).x - 26 * FS); ix = n.dx + n.b.w + 16 * FS; ih = Math.max(ih, n.b.h); w = Math.max(w, n.dx + n.b.w + PAD()); }
        if (inner.length) h += 26 * FS + ih + PAD();
        return { c, mi, x0, inner, w, h }; });
      return { pm, ps, secs, w: Math.max(...secs.map((s) => s.w)), h: secs.reduce((a, s) => a + s.h, 0) };
    }
    function putNest(b, X, Y) {
      L.frames.push({ type: "box", m: b.secs[0].c, host: key(b.pm, b.ps), x: X, y: Y, w: b.w, h: b.h, kind: primary[b.secs[0].c].kind });
      let y = Y;
      for (const s of b.secs) { L.titles.push({ m: s.c, x: X + 12 * FS, y: y + 14 * FS });
        const oy = y + TTL() + LAB() - s.mi.top; placeMini(s.c, X + s.x0, oy, s.mi);
        for (const n of s.inner) putNest(n.b, X + n.dx, oy + s.mi.bot + LAB() + 26 * FS);
        y += s.h; }
    }
    function layNest() {
      L = newLayout(); const g = G[IP], rowGap = 52 * FS, gapV = 54 * FS;
      let y = shelf(dagOnly.map((c, i) => hullItem(c, { want: (CW * (i + 1)) / (dagOnly.length + 1), kind: "dag" })), 0);
      const y0 = y + gapV + 60 * FS - g.rmin * rowGap;
      y = trunk(y0, rowGap, 70 * FS) + 46 * FS;
      const comp = M[IP].states.filter((s) => kidsAt(IP, s.id).length).map((s) => s.id);
      y = shelf(comp.map((s) => { const b = nestBox(IP, s); return { w: b.w, h: b.h, want: node(IP, s).x - 40 * FS + b.w / 2, put: (x0, yy) => putNest(b, x0, yy) }; }), y) + gapV;
      dock(y);
      tiesFor([]);
      return L;
    }

    // metro: a line per machine, stations spaced by their labels; a branch leaves its station at 45° and hooks back
    function lineItem(c, o = {}) {
      const g = G[c], step = miniGap(c) * 1.1, rg = 32 * FS, lead = o.dag ? 40 * FS : 0, w = Math.max(lead + (g.ncols - 1) * step + 40 * FS, titleW(c) + 10 * FS), h = 44 * FS + LAB() + (g.rmax - g.rmin) * rg + LAB();
      return { c, w, h, want: o.want, put(x0, y0) { const sx = x0 + lead + 10 * FS, gy = y0 + 44 * FS + LAB() - g.rmin * rg;
        for (const st of M[c].states) addNode(c, st.id, sx + g.depth[st.id] * step, gy + g.row[st.id] * rg, { sides: sidesFor(c, st.id) });
        trackLines(c, o.dim ? 2.5 : 3.5, o.dim); L.titles.push({ m: c, x: x0, y: y0 + 8 * FS, dim: o.dim });
        dagTies(c).forEach((t, k) => { const gl = glyph(t.dag, sx - 30 * FS, gy - k * 22 * FS, c, true); L.tracks.push({ m: c, pts: [{ x: gl.x, y: gl.y }, { x: sx, y: gy }], w: 2, dag: true }); }); } };
    }
    function layMetro() {
      L = newLayout(); const g = G[IP], rowGap = 50 * FS, gapV = 54 * FS, rg = 32 * FS;
      let y = shelf(dagOnly.map((c, i) => lineItem(c, { want: (CW * (i + 1)) / (dagOnly.length + 1), dag: true })), 0);
      const y0 = y + gapV + 60 * FS - g.rmin * rowGap;
      const tb = trunk(y0, rowGap, 60 * FS); trackLines(IP, 5);
      const s0 = node(IP, initOf(IP)); for (const gl of L.glyphs.filter((x) => x.child === IP)) L.tracks.push({ m: IP, pts: [{ x: gl.x, y: gl.y }, { x: s0.x, y: s0.y }], w: 2, dag: true });
      const lines = [], levelTop = tb + 70 * FS;
      const byLevel = {}; for (const c of tied) (byLevel[depthOf(c)] ||= []).push(c);
      let bottom = tb;
      for (const lvl of Object.keys(byLevel).map(Number).sort()) for (const c of byLevel[lvl].sort((a, b) => node(primary[a].pm, primary[a].ps).x - node(primary[b].pm, primary[b].ps).x)) {
        const p = primary[c], P0 = node(p.pm, p.ps), cg = G[c], step = miniGap(c) * 1.1, h = 44 * FS + LAB() + (cg.rmax - cg.rmin) * rg + LAB();
        // the first level below the parent with room for this line
        let top = Math.max(levelTop, P0.y + 60 * FS);
        for (;;) { const gy = top + 44 * FS + LAB() - cg.rmin * rg, x1 = P0.x + Math.max(26 * FS, gy - P0.y), x2 = x1 + 20 * FS + (cg.ncols - 1) * step + 120 * FS;
          const clash = lines.find((o) => !(top > o.bot + 16 * FS || top + h < o.top - 16 * FS) && !(P0.x > o.x2 + 20 * FS || x2 < o.x0 - 20 * FS));
          if (!clash) { lines.push({ c, top, bot: top + h, x0: P0.x, x2, gy, x1 }); break; } top = clash.bot + 24 * FS; }
        const b = lines.at(-1), lw = 20 * FS + (cg.ncols - 1) * step + 130 * FS + textW(stName(p.pm, p.ps), 10 * FS), sx = Math.min(b.x1 + 20 * FS, CW - 20 * FS - lw + 20 * FS); b.x1 = sx - 20 * FS;
        const run = Math.abs(b.x1 - P0.x), legPts = run < b.gy - P0.y ? [{ x: P0.x, y: P0.y }, { x: P0.x, y: b.gy - run }, { x: b.x1, y: b.gy }] : [{ x: P0.x, y: P0.y }, { x: b.x1, y: b.gy }];
        for (const st of M[c].states) addNode(c, st.id, sx + cg.depth[st.id] * step, b.gy + cg.row[st.id] * rg, { sides: sidesFor(c, st.id) });
        L.tracks.push({ m: c, pts: [...legPts, { x: sx, y: b.gy }], w: 4, link: true, kind: p.kind });
        trackLines(c, 3.5);
        const end = node(c, cg.mainList.at(-1)); L.frames.push({ type: "hook", m: c, x: end.x + 20 * FS, y: end.y, to: stName(p.pm, p.ps) });
        L.titles.push({ m: c, x: Math.max(sx + 8 * FS, legPts[1].x + 14 * FS), y: b.top + 8 * FS });
        dagTies(c).forEach((t, k) => glyph(t.dag, sx - 4 * FS - k * 0, b.gy + 40 * FS + k * 22 * FS, c));
        bottom = Math.max(bottom, b.bot);
      }
      dock(bottom + gapV);
      tiesFor([]);
      return L;
    }
    // metro track between two states one column apart: straight, else a horizontal run then a 45° leg
    function trackLines(m, w, dim) {
      const g = G[m], seen = new Set();
      for (const t of M[m].trans) { const a = node(m, t.source), b = node(m, t.target), k2 = [t.source, t.target].sort().join("|"); if (!a || !b || seen.has(k2)) continue;
        if (Math.abs(g.depth[t.source] - g.depth[t.target]) !== 1) continue; seen.add(k2);
        const [p, q] = a.x <= b.x ? [a, b] : [b, a], dy = q.y - p.y, run = Math.max(0, q.x - p.x - Math.abs(dy));
        const pts = Math.abs(dy) < 1 ? [p, q] : [p, { x: p.x + run / 2, y: p.y }, { x: q.x - run / 2, y: q.y }, q];
        L.tracks.push({ m, pts: pts.map((o) => ({ x: o.x, y: o.y })), w: g.main.has(t.source) && g.main.has(t.target) ? w : w * 0.55, dim }); }
    }

    // orbit: arc along the in-progress ring shared out by what each state carries; sub-machines ring their state
    function layOrbit() {
      L = newLayout(); const g = G[IP]; L.centre = { x: 0, y: 0 };
      const ringR = (c) => Math.max(76, M[c].states.length * 15) * FS + 12;
      const order = M[IP].states.map((s) => s.id).sort((a, b) => g.depth[a] - g.depth[b] || g.row[a] - g.row[b]);
      const need = order.map((s) => { const ks = kidsAt(IP, s); return ks.length ? 2 * ringR(ks[0]) + 120 * FS : 92 * FS; });
      const total = need.reduce((a, b) => a + b, 0), asp = 1.5, per = (b) => { const a = asp * b; return Math.PI * (3 * (a + b) - Math.sqrt((3 * a + b) * (a + 3 * b))); };
      const big = Math.max(0, ...M[IP].states.flatMap((s) => kidsAt(IP, s.id).map(ringR)));
      let ry = Math.max(120 * FS, big + 120 * FS); while (per(ry) < total) ry += 4; const rx = asp * ry;
      let acc = 0;
      order.forEach((s, i) => { const th = Math.PI + (TAU * (acc + need[i] / 2)) / total; acc += need[i];
        addNode(IP, s, rx * Math.cos(th), ry * Math.sin(th), { phi: th, sides: ["out", "in"] }); });
      // a machine's ring: its states as beads round a centre, the bead that opens another machine facing out
      function ring(m, x, y, R, out, o = {}) {
        const g2 = G[m], ids = M[m].states.map((s) => s.id).sort((a, b) => g2.depth[a] - g2.depth[b] || g2.row[a] - g2.row[b]);
        const ki = ids.findIndex((s) => kidsAt(m, s).length), kdir = out + (ki < 0 || !o.host ? 0 : 0.6), base = ki < 0 ? -Math.PI / 2 : kdir - (ki * TAU) / ids.length;
        ids.forEach((s, i) => { const th = base + (i * TAU) / ids.length; addNode(m, s, x + R * Math.cos(th), y + R * Math.sin(th), { phi: th, sides: ["out", "in"] }); });
        L.frames.push({ type: "ring", m, x, y, r: R, host: o.host, kind: o.kind, dim: o.dim });
        const tdir = out - (ki < 0 || !o.host ? 0 : 0.6), tx = Math.cos(tdir), ty = Math.sin(tdir), tdist = R + 30 * FS, px = TPX();
        L.titles.push({ m, x: x + tx * tdist, y: y + ty * tdist + (ty < -0.5 ? -2.1 * px : ty > 0.5 ? 0.6 * px : -0.6 * px), align: tx > 0.5 ? "left" : tx < -0.5 ? "right" : "center", dim: o.dim });
        const ux = Math.cos(kdir), uy = Math.sin(kdir);
        for (const st of ids) for (const c of kidsAt(m, st)) { const b = node(m, st), R2 = ringR(c), d = R + R2 + 110 * FS, cx2 = x + ux * d, cy2 = y + uy * d;
          L.frames.push({ type: "stalk", m: c, x1: b.x, y1: b.y, x2: cx2 - ux * R2, y2: cy2 - uy * R2, kind: primary[c].kind });
          ring(c, cx2, cy2, R2, out, { host: b.key, kind: primary[c].kind }); }
      }
      // a ring's DAG stars side by side at its centre; the title names them
      function starsAt(c, x, y) { const ts = dagTies(c); ts.forEach((t, k) => glyph(t.dag, x + (k - (ts.length - 1) / 2) * 18 * FS, y, c, true)); }
      let ext = { x0: -rx, x1: rx, y0: -ry, y1: ry };
      for (const s of order) for (const c of kidsAt(IP, s)) { const p = node(IP, s); p.labelR = ringR(c) + 8 * FS; ring(c, p.x, p.y, ringR(c), p.phi, { host: p.key, kind: primary[c].kind }); }
      for (const n of L.nodes.values()) ext = { x0: Math.min(ext.x0, n.x - 110 * FS), x1: Math.max(ext.x1, n.x + 110 * FS), y0: Math.min(ext.y0, n.y), y1: Math.max(ext.y1, n.y) };
      for (const t of L.titles) { const w = titleW(t.m), x0 = t.align === "right" ? t.x - w : t.align === "center" ? t.x - w / 2 : t.x; ext = { ...ext, x0: Math.min(ext.x0, x0), x1: Math.max(ext.x1, x0 + w) }; }
      // below the ring, in rows as wide as the region: DAG-launched machines round their DAG's star, then machines with no tie, dim
      for (const t of L.titles) ext.y1 = Math.max(ext.y1, t.y + 2.4 * TPX());
      function ringRow(list, y, o) {
        const items = list.map((c) => { const R = o.small ? Math.max(36, M[c].states.length * 8) * FS : ringR(c), lw = Math.max(...M[c].states.map((st) => labW(c, st.id)));
          return { c, R, w: Math.max(2 * R + 2 * lw + 24 * FS, titleW(c) + 24 * FS), h: 2 * R + 2 * MPX() + 30 * FS + 2.4 * TPX() + 18 * FS }; });
        const rows = [[]]; let used = 0;
        for (const it of items) { if (rows.at(-1).length && used + it.w > CW) { rows.push([]); used = 0; } rows.at(-1).push(it); used += it.w; }
        for (const row of rows) { const top = y + 2 * MPX(); let x = -row.reduce((a, it) => a + it.w, 0) / 2;
          for (const it of row) { const cx2 = x + it.w / 2, cy2 = top + it.R; ring(it.c, cx2, cy2, it.R, Math.PI / 2, { kind: o.kind, dim: o.dim }); if (o.kind === "dag") starsAt(it.c, cx2, cy2); x += it.w; }
          y += Math.max(...row.map((it) => it.h)); }
        return y;
      }
      let rowY = ext.y1 + 70 * FS;
      if (dagOnly.length) rowY = ringRow(dagOnly, rowY, { kind: "dag" }) + 30 * FS;
      if (dormant.length) { L.titles.push({ caption: "no tie in this window", x: 0, y: rowY, align: "center" }); ringRow(dormant, rowY + 26 * FS, { kind: "none", dim: true, small: true }); }
      for (const c of tied) { const f = L.frames.find((fr) => fr.type === "ring" && fr.m === c); if (f) starsAt(c, f.x, f.y); }
      L.titles.push({ m: IP, x: 0, y: -14 * FS, align: "center", big: true });
      for (const t of dagTies(IP)) glyph(t.dag, -textW(t.dag, 10 * FS) / 2 - 6 * FS, 34 * FS, IP);
      tiesFor([]);
      return L;
    }

    // the ties each variant draws as lines: a machine's primary tie where placement does not show it (satellites),
    // DAG launches whose star stands apart from the machine, and every other observed tie, shown on hover or focus
    function tieEnd(child, from) { const f = L.frames.find((fr) => fr.m === child && (fr.type === "hull" || fr.type === "box"));
      if (f) return { x: clamp(from.x, f.x + 24 * FS, f.x + f.w - 24 * FS), y: from.y < f.y ? f.y : f.y + f.h };
      const r = L.frames.find((fr) => fr.m === child && fr.type === "ring"); if (r) { const a = Math.atan2(from.y - r.y, from.x - r.x); return { x: r.x + r.r * Math.cos(a), y: r.y + r.r * Math.sin(a) }; }
      return node(child, initOf(child)); }
    function tiesFor(drawn) {
      for (const t of TIES) {
        if (t.kind === "dag") continue; // every variant stands a DAG's star on the machine it launches
        const a = node(t.pm, t.ps); if (!a) continue;
        const isPrimary = primary[t.child] === t;
        if (isPrimary && !drawn.includes("primary")) continue;
        L.ties.push({ t, a, b: tieEnd(t.child, a), sec: !isPrimary });
      }
    }
    const tieShown = (d) => !d.sec || focus === d.t.child || (hover?.kind === "node" && hover.o.m === d.t.pm && hover.o.s === d.t.ps) || (hover?.kind === "frame" && hover.o.m === d.t.child) || (hover?.kind === "tie" && hover.o === d);

    // ---- view: the layout fitted between the navigator and the rail, below the note and above the switcher
    let vb = null, view = { k: 1, x: 0, y: 0 }, fitK = 1, focus = P.get("focus") || null, pinned = null, hover = null, labels = [], labelKey = "";
    function bounds(u = 1) { let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity; const add = (x, y, r = 0) => { x0 = Math.min(x0, x - r); x1 = Math.max(x1, x + r); y0 = Math.min(y0, y - r); y1 = Math.max(y1, y + r); };
      for (const n of L.nodes.values()) { const lw = (labW(n.m, n.s) * (L.kind === "orbit" ? 1 : 0.5) + 8) * u, lr = n.labelR ?? n.r; add(n.x - lr - lw, n.y - lr - 22 * FS * u); add(n.x + lr + lw, n.y + lr + 22 * FS * u); }
      for (const f of L.frames) { if (f.w) { add(f.x, f.y); add(f.x + f.w, f.y + f.h); } else if (f.r) add(f.x, f.y, f.r + 20 * FS); }
      for (const g of L.glyphs) { add(g.x, g.y, 14 * FS * u); if (!g.quiet) add(g.x + (14 * FS + textW(g.dag, 10 * FS)) * u, g.y); }
      for (const t of L.titles) { const w = (t.caption ? textW(t.caption, 11 * FS) : titleW(t.m, t.big)) * u, x = t.align === "center" ? t.x - w / 2 : t.align === "right" ? t.x - w : t.x; add(x, t.y - 10 * FS * u); add(x + w, t.y + 24 * FS * u); }
      return { x0, y0, x1, y1 }; }
    const TOP = () => 46 * FS, FOOT = () => 54 * FS;
    function relayout(keepView) {
      readFS(); wcache.clear(); ({ sat: laySat, nest: layNest, metro: layMetro, orbit: layOrbit })[MV](); layoutId++;
      // fit the width; a layout taller than the window scrolls rather than shrinking its text into collisions
      const avH = CH - TOP() - FOOT(), fitOf = (b) => Math.min(1, (CW - 24) / (b.x1 - b.x0), Math.max(0.85, avH / (b.y1 - b.y0)));
      let k = 1, b = bounds(1); for (let i = 0; i < 6; i++) { k = fitOf(b); b = bounds(1 / k); } k = Math.min(fitOf(b), fitOf(bounds(1 / (fitOf(b) * 0.97))));
      fitK = k; vb = b; const tall = (b.y1 - b.y0) * k > avH;
      if (!keepView) view = { k, x: CW / 2 - ((b.x0 + b.x1) / 2) * k, y: tall ? TOP() - b.y0 * k : TOP() + avH / 2 - ((b.y0 + b.y1) / 2) * k };
      labelKey = "";
    }
    function resize() { DPR = devicePixelRatio || 1; W = innerWidth; H = innerHeight; CW = W - NAVW - RAILW; CH = H; cv.width = W * DPR; cv.height = H * DPR; cv.style.width = `${W}px`; cv.style.height = `${H}px`; relayout(); renderBar(); }
    const toScreen = (x, y) => ({ x: NAVW + view.x + x * view.k, y: view.y + y * view.k });
    const toWorld = (sx, sy) => ({ x: (sx - NAVW - view.x) / view.k, y: (sy - view.y) / view.k });

    // ---- labels: each state's name on the side that overlaps least, titles first so states give way to them
    const overlap = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
    function circRect(c, r) { const dx = Math.max(r.x0 - c.x, 0, c.x - r.x1), dy = Math.max(r.y0 - c.y, 0, c.y - r.y1), d = Math.hypot(dx, dy); return d < c.r ? (c.r - d) * 12 : 0; }
    function placeLabels() {
      const k = `${layoutId}|${view.k.toFixed(4)}|${view.x.toFixed(1)}|${view.y.toFixed(1)}|${FS}|${counts()}`; if (k === labelKey) return; labelKey = k;
      labels = []; const placed = [], circles = [];
      for (const n of L.nodes.values()) { const p = toScreen(n.x, n.y); circles.push({ x: p.x, y: p.y, r: n.r * view.k + 3, n }); }
      for (const g of L.glyphs) { const p = toScreen(g.x, g.y), w = g.quiet ? 0 : textW(g.dag, 10 * FS); placed.push({ x0: p.x - 8, x1: p.x + 12 * FS + w, y0: p.y - 8 * FS, y1: p.y + 8 * FS }); }
      for (const f of L.frames) if (f.type === "hook") { const p = toScreen(f.x, f.y), y = p.y - 16 * FS * view.k; placed.push({ x0: p.x, x1: p.x + 8 * FS + textW(`↩ ${f.to}`, 10 * FS), y0: y - 8 * FS, y1: y + 8 * FS }); }
      for (const t of L.titles) { const px = TPX(t.big), txt = t.caption || t.m, sub = t.caption ? "" : subTitle(t.m), w = t.caption ? textW(txt, 11 * FS) : titleW(t.m, t.big), p = toScreen(t.x, t.y);
        const x0 = t.align === "center" ? p.x - w / 2 : t.align === "right" ? p.x - w : p.x, r = { x0, x1: x0 + w, y0: p.y - px * 0.7, y1: p.y + (sub ? px * 1.9 : px * 0.7) };
        placed.push(r); labels.push({ title: t, txt, sub, px: t.caption ? 11 * FS : px, x: x0, y: p.y, w }); }
      const order = [...L.nodes.values()].sort((a, b) => (b.m === IP) - (a.m === IP) || M[b.m].agents.filter((x) => x.state === b.s).length - M[a.m].agents.filter((x) => x.state === a.s).length);
      for (const n of order) {
        const px = n.m === IP ? IPX() : MPX(), cnt = tasksAt(n.m, n.s).length, w = textW(n.label, px) + (cnt ? textW(` ${cnt}`, px * 0.9) + 2 : 0), h = px * 1.25, p = toScreen(n.x, n.y), rr = (n.labelR ?? n.r) * view.k, gap = 4;
        const cands = (n.sides || ["below", "above", "right", "left"]).map((side) => {
          if (side === "below") return { x0: p.x - w / 2, y0: p.y + rr + gap, side };
          if (side === "above") return { x0: p.x - w / 2, y0: p.y - rr - gap - h, side };
          if (side === "right") return { x0: p.x + rr + gap + 2, y0: p.y - h / 2, side };
          if (side === "left") return { x0: p.x - rr - gap - 2 - w, y0: p.y - h / 2, side };
          const ph = side === "out" ? n.phi : n.phi + Math.PI, c = Math.cos(ph), s = Math.sin(ph), ax = p.x + c * (rr + gap + 2), ay = p.y + s * (rr + gap + 2);
          return { x0: c > 0.35 ? ax : c < -0.35 ? ax - w : ax - w / 2, y0: Math.abs(c) > 0.35 ? ay - h / 2 : s > 0 ? ay : ay - h, side }; });
        let best = null, bestCost = Infinity;
        for (const c of cands) { const r = { x0: c.x0, y0: c.y0, x1: c.x0 + w, y1: c.y0 + h }, pad = { x0: r.x0 - 4, x1: r.x1 + 4, y0: r.y0 - 1, y1: r.y1 + 1 }; let cost = 0;
          for (const q of placed) cost += overlap(pad, q); for (const ci of circles) if (ci.n !== n) cost += circRect(ci, r);
          if (cost < bestCost - 0.5) { best = r; bestCost = cost; } if (!cost) break; }
        placed.push(best); labels.push({ node: n, txt: n.label, cnt, px, x: best.x0, y: best.y0 + h / 2, w });
      }
    }
    const counts = () => Object.values(M).map((m) => m.agents.map((a) => a.state).join()).join("|");
    function subTitle(m) {
      if (m === IP) { const d = dagTies(IP).map((t) => t.dag); return `${M[m].states.length} states · ${M[m].agents.length} tasks${d.length ? ` · launched by ${d.join(", ")}` : ""}`; }
      const p = primary[m], d = dagTies(m), o = others(m), n = M[m].agents.length;
      const from = p ? (p.kind === "declared" ? `opens from ${stName(p.pm, p.ps)}` : `entered from ${stName(p.pm, p.ps)} ×${p.count}`) : d.length ? `launched by ${d.map((t) => t.dag).join(", ")}` : "no tie in this window";
      return `${n} session${n === 1 ? "" : "s"}${seeded.has(m) ? " (seeded)" : ""} · ${from}${o.length ? ` · +${o.length} more` : ""}${p && d.length ? ` · launched by ${d.map((t) => t.dag).join(", ")}` : ""}`;
    }

    // ---- drawing
    const stars = Array.from({ length: 260 }, (_, i) => ({ x: (Math.sin(i * 12.9898) * 43758.5453) % 1, y: (Math.sin(i * 78.233) * 12543.123) % 1, r: 0.3 + ((i * 7) % 10) / 14, t: i }));
    let T = 0, last = performance.now();
    const dimOf = (m) => (focus && !lineage(focus).has(m) ? 0.16 : 1);
    const kindDash = (kind, s = 1) => (kind === "observed" ? [6 * s / view.k, 4 * s / view.k] : kind === "dag" ? [1.5 / view.k, 4 / view.k] : kind === "none" ? [2 / view.k, 6 / view.k] : []);
    function drawFrames() {
      for (const f of L.frames) { const col = colOf(f.m), a = dimOf(f.m) * (f.dim ? 0.6 : 1), hot = (hover?.kind === "frame" && hover.o === f) || focus === f.m;
        cx.lineWidth = (hot ? 1.6 : 1) / view.k;
        if (f.type === "hull") { cx.strokeStyle = rgba(col, (hot ? 0.55 : 0.22) * a); cx.fillStyle = rgba(col, 0.035 * a); cx.setLineDash(kindDash(f.kind || "observed", 0.7)); roundRect(f.x, f.y, f.w, f.h, 12 * FS); cx.fill(); cx.stroke(); cx.setLineDash([]); }
        if (f.type === "box") { // the host state's outline runs down a neck into the box it holds
          const h = L.nodes.get(f.host), hc = colOf(h.m), nx = clamp(h.x, f.x + 22 * FS, f.x + f.w - 22 * FS), nw = Math.min(h.r * 0.8, 10 * FS);
          cx.fillStyle = rgba(col, 0.045 * a); cx.strokeStyle = rgba(hc, (hot ? 0.85 : 0.5) * a); cx.setLineDash(kindDash(f.kind));
          cx.beginPath(); cx.moveTo(h.x - nw, h.y + h.r * 0.6); cx.lineTo(nx - nw - 6 * FS, f.y); cx.lineTo(f.x + 10 * FS, f.y); cx.arcTo(f.x, f.y, f.x, f.y + 10 * FS, 10 * FS);
          cx.lineTo(f.x, f.y + f.h - 10 * FS); cx.arcTo(f.x, f.y + f.h, f.x + 10 * FS, f.y + f.h, 10 * FS); cx.lineTo(f.x + f.w - 10 * FS, f.y + f.h); cx.arcTo(f.x + f.w, f.y + f.h, f.x + f.w, f.y + f.h - 10 * FS, 10 * FS);
          cx.lineTo(f.x + f.w, f.y + 10 * FS); cx.arcTo(f.x + f.w, f.y, f.x + f.w - 10 * FS, f.y, 10 * FS); cx.lineTo(nx + nw + 6 * FS, f.y); cx.lineTo(h.x + nw, h.y + h.r * 0.6); cx.fill(); cx.stroke(); cx.setLineDash([]); }
        if (f.type === "ring") { cx.strokeStyle = rgba(col, (hot ? 0.7 : 0.34) * a); cx.setLineDash(kindDash(f.kind)); cx.lineWidth = (hot ? 2.2 : 1.4) / view.k;
          cx.beginPath(); cx.arc(f.x, f.y, f.r, 0, TAU); cx.stroke(); cx.setLineDash([]); cx.fillStyle = rgba(col, 0.035 * a); cx.fill(); }
        if (f.type === "stalk") { cx.strokeStyle = rgba(col, 0.55 * a); cx.lineWidth = 1.4 / view.k; cx.setLineDash(kindDash(f.kind)); cx.beginPath(); cx.moveTo(f.x1, f.y1); cx.lineTo(f.x2, f.y2); cx.stroke(); cx.setLineDash([]); }
        if (f.type === "hook") { cx.strokeStyle = rgba(col, 0.55 * a); cx.lineWidth = 2.5 / view.k; cx.beginPath(); cx.moveTo(f.x - 16 * FS, f.y); cx.lineTo(f.x, f.y); cx.arc(f.x, f.y - 8 * FS, 8 * FS, Math.PI / 2, -Math.PI / 2, true); cx.stroke(); }
      }
      for (const tr of L.tracks) { const col = tr.dag ? DAGC : colOf(tr.m), a = dimOf(tr.m) * (tr.dim ? 0.45 : 1), hot = focus === tr.m || (hover?.kind === "frame" && hover.o.m === tr.m);
        cx.strokeStyle = rgba(col, (tr.dag ? 0.6 : hot ? 0.75 : 0.42) * a); cx.lineWidth = tr.w * (tr.dag ? 0.6 : 1) * Math.min(1, FS); cx.lineJoin = "round"; cx.lineCap = "round";
        cx.setLineDash(tr.dag ? [1.5, 5] : tr.link && tr.kind === "observed" ? [7, 5] : []); cx.beginPath(); tr.pts.forEach((p, i) => (i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y))); cx.stroke(); cx.setLineDash([]); }
    }
    function roundRect(x, y, w, h, r) { cx.beginPath(); cx.moveTo(x + r, y); cx.arcTo(x + w, y, x + w, y + h, r); cx.arcTo(x + w, y + h, x, y + h, r); cx.arcTo(x, y + h, x, y, r); cx.arcTo(x, y, x + w, y, r); cx.closePath(); }
    function curve(a, b, bend = 0.15) { const dx = b.x - a.x, dy = b.y - a.y; return { p0: a, p1: b, c: { x: (a.x + b.x) / 2 - dy * bend, y: (a.y + b.y) / 2 + dx * bend } }; }
    const bez = (e, t) => { const u = 1 - t; return { x: u * u * e.p0.x + 2 * u * t * e.c.x + t * t * e.p1.x, y: u * u * e.p0.y + 2 * u * t * e.c.y + t * t * e.p1.y }; };
    function edgeCurve(m, a, b) { if (L.centre && m === IP) { const c = L.centre, mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }; return { p0: a, p1: b, c: { x: mid.x + (c.x - mid.x) * 0.2, y: mid.y + (c.y - mid.y) * 0.2 } }; }
      return curve(a, b, 0.12); }
    function drawEdges() {
      for (const m of Object.keys(M)) { const a = dimOf(m), g = G[m];
        for (const t of M[m].trans) { const p = node(m, t.source), q = node(m, t.target); if (!p || !q) continue;
          if (L.kind === "metro" && Math.abs(g.depth[t.source] - g.depth[t.target]) === 1) continue;
          const e = edgeCurve(m, p, q), hot = hover?.kind === "node" && (hover.o === p || hover.o === q);
          cx.strokeStyle = rgba(colOf(m), (hot ? 0.6 : m === IP ? 0.24 : L.kind === "orbit" ? 0.11 : 0.2) * a); cx.lineWidth = (hot ? 1.4 : 1) / view.k; cx.setLineDash(L.kind === "metro" ? [2 / view.k, 4 / view.k] : []);
          cx.beginPath(); cx.moveTo(e.p0.x, e.p0.y); cx.quadraticCurveTo(e.c.x, e.c.y, e.p1.x, e.p1.y); cx.stroke(); cx.setLineDash([]);
          if (L.kind !== "metro") { const u = 0.62, p1 = bez(e, u), p2 = bez(e, u + 0.04), ang = Math.atan2(p2.y - p1.y, p2.x - p1.x), s = 4 / view.k; cx.fillStyle = rgba(colOf(m), (hot ? 0.7 : 0.32) * a);
            cx.beginPath(); cx.moveTo(p2.x, p2.y); cx.lineTo(p2.x - s * Math.cos(ang - 0.5), p2.y - s * Math.sin(ang - 0.5)); cx.lineTo(p2.x - s * Math.cos(ang + 0.5), p2.y - s * Math.sin(ang + 0.5)); cx.fill(); } } }
    }
    const tieCurve = (d) => curve(d.a, d.b, d.t.kind === "dag" ? 0.05 : d.sec ? (d.a.x < d.b.x ? -0.12 : 0.12) : 0.04);
    function drawTies(now) {
      for (const d of L.ties) { d.mid = null; if (!tieShown(d)) continue;
        const e = tieCurve(d), col = d.t.kind === "dag" ? DAGC : colOf(d.t.child), a = Math.min(dimOf(d.t.child), d.t.pm ? dimOf(d.t.pm) : 1);
        const hot = (hover?.kind === "tie" && hover.o === d) || focus === d.t.child, fl = Math.max(0, 1 - (now - d.t.flash) / 1600);
        cx.strokeStyle = rgba(fl ? ACT : col, Math.min(1, (hot ? 0.9 : d.sec ? 0.45 : 0.62) * a + fl));
        cx.lineWidth = (d.t.kind === "observed" ? 1 + Math.log2(1 + d.t.count) * 0.7 : d.t.kind === "declared" ? 2.2 : 1.3) / view.k ** 0.6;
        cx.setLineDash(kindDash(d.t.kind));
        cx.beginPath(); cx.moveTo(e.p0.x, e.p0.y); cx.quadraticCurveTo(e.c.x, e.c.y, e.p1.x, e.p1.y); cx.stroke(); cx.setLineDash([]);
        d.mid = bez(e, d.sec ? 0.5 : 0.55); }
    }
    function drawGlyph(g) { const a = dimOf(g.child), r = (6 * FS) / Math.max(0.6, view.k ** 0.5), hot = hover?.kind === "glyph" && hover.o === g; cx.fillStyle = rgba(DAGC, (hot ? 1 : 0.85) * a);
      cx.beginPath(); for (let i = 0; i < 8; i++) { const rr = i % 2 ? r * 0.32 : r, th = (i * Math.PI) / 4 - Math.PI / 2; cx.lineTo(g.x + rr * Math.cos(th), g.y + rr * Math.sin(th)); } cx.closePath(); cx.fill();
      cx.fillStyle = rgba(DAGC, 0.12 * a); cx.beginPath(); cx.arc(g.x, g.y, r * 1.8, 0, TAU); cx.fill(); }
    function drawNodes() {
      for (const n of L.nodes.values()) { const col = colOf(n.m), a = dimOf(n.m), hot = hover?.kind === "node" && hover.o === n;
        cx.fillStyle = "#05070d"; cx.beginPath(); cx.arc(n.x, n.y, n.r, 0, TAU); cx.fill();
        cx.fillStyle = rgba(col, (hot ? 0.34 : 0.16) * a); cx.fill();
        cx.strokeStyle = rgba(col, (hot ? 1 : 0.75) * a); cx.lineWidth = (hot ? 1.8 : 1.2) / view.k ** 0.5; cx.stroke();
        if (n.final) { cx.strokeStyle = rgba(col, 0.45 * a); cx.beginPath(); cx.arc(n.x, n.y, n.r + 3 / view.k ** 0.5, 0, TAU); cx.stroke(); }
        if (n.initial) { cx.fillStyle = rgba(col, 0.9 * a); cx.beginPath(); cx.arc(n.x, n.y, Math.min(2.4, n.r * 0.35), 0, TAU); cx.fill(); }
        const ks = kidsAt(n.m, n.s); if (ks.length && L.kind !== "nest") { cx.strokeStyle = rgba(colOf(ks[0]), 0.75 * a); cx.setLineDash([2 / view.k, 2 / view.k]); cx.beginPath(); cx.arc(n.x, n.y, n.r + 6 / view.k ** 0.5, 0, TAU); cx.stroke(); cx.setLineDash([]); } }
    }
    // tasks orbit the state they sit on; a moving task rides the path to its next state
    const dotR = () => 2.3 / Math.max(0.7, view.k ** 0.5);
    function slots(n, i) { const base = n.r + 5, sp = 6.2; let ring = 0, rem = i, R = base;
      for (;;) { const cap = Math.max(6, Math.floor((TAU * R) / sp)); if (rem < cap) return { R, a: (rem / cap) * TAU }; rem -= cap; ring++; R = base + ring * 5.5; } }
    const taskPos = new Map();
    function drawTasks(now) {
      taskPos.clear();
      const hl = hover?.kind === "task" ? hover.o.task : pinned?.task;
      for (const n of L.nodes.values()) { const list = tasksAt(n.m, n.s), a = dimOf(n.m);
        list.forEach((ag, i) => { const sl = slots(n, i), th = sl.a + T * 0.06 * (sl.R < 30 ? 1 : 0.6), x = n.x + sl.R * Math.cos(th), y = n.y + sl.R * Math.sin(th);
          taskPos.set(ag, { x, y }); const on = hl && ag.task === hl;
          cx.fillStyle = rgba(TIER[tierOf(ag.model)], (on ? 1 : 0.85) * a); cx.beginPath(); cx.arc(x, y, dotR() * (on ? 1.6 : 1), 0, TAU); cx.fill();
          if (ag.kind === "unattended") { cx.strokeStyle = rgba("#05070d", a); cx.lineWidth = 0.8 / view.k; cx.stroke(); }
          if (now - (ag.landed || -1e9) < 1400) pulse(x, y, (now - ag.landed) / 1400); }); }
      for (const m of Object.values(M)) for (const ag of m.agents) if (ag.move) { const fr = ag.move.fromGlyph || L.nodes.get(ag.move.from), to = node(ag.m, ag.state); if (!fr || !to) { ag.move = null; continue; }
        const u = Math.min(1, (now - ag.move.t0) / 1400), e = curve(fr, to, 0.18), p = bez(e, easeO(u));
        cx.strokeStyle = rgba(ACT, 0.5); cx.lineWidth = 1.5 / view.k; cx.beginPath(); const p0 = bez(e, Math.max(0, easeO(u) - 0.12)); cx.moveTo(p0.x, p0.y); cx.lineTo(p.x, p.y); cx.stroke();
        cx.fillStyle = ACT; cx.beginPath(); cx.arc(p.x, p.y, dotR() * 1.5, 0, TAU); cx.fill(); taskPos.set(ag, p);
        if (u >= 1) { ag.move = null; ag.landed = now; } }
      if (hl) { const pts = (byTask[hl] || []).map((ag) => taskPos.get(ag)).filter(Boolean); cx.strokeStyle = rgba("#fde68a", 0.55); cx.lineWidth = 1 / view.k; cx.setLineDash([3 / view.k, 3 / view.k]);
        for (let i = 1; i < pts.length; i++) { cx.beginPath(); cx.moveTo(pts[0].x, pts[0].y); cx.lineTo(pts[i].x, pts[i].y); cx.stroke(); } cx.setLineDash([]);
        for (const p of pts) { cx.strokeStyle = rgba("#fde68a", 0.9); cx.beginPath(); cx.arc(p.x, p.y, dotR() * 3, 0, TAU); cx.stroke(); } }
    }
    function pulse(x, y, u) { cx.strokeStyle = rgba(ACT, 0.7 * (1 - u)); cx.lineWidth = 1.2 / view.k; cx.beginPath(); cx.arc(x, y, (3 + 18 * u) / view.k ** 0.5, 0, TAU); cx.stroke(); }
    function drawLabels() {
      placeLabels();
      for (const l of labels) {
        if (l.title) { const t = l.title, col = t.caption ? "#6b7a93" : colOf(t.m), a = t.m ? dimOf(t.m) : 1;
          cx.globalAlpha = a * (t.dim ? 0.65 : 1); text(l.txt, l.x, l.y, l.px, col, "left", t.caption ? 400 : 500);
          if (l.sub) text(l.sub, l.x, l.y + l.px * 1.2, l.px * 0.85, "#7b879b", "left", 400); cx.globalAlpha = 1; continue; }
        const n = l.node, a = dimOf(n.m), hot = hover?.kind === "node" && hover.o === n;
        cx.globalAlpha = a; text(l.txt, l.x, l.y, l.px, hot ? "#dbe4f3" : n.m === IP ? "#aab6cc" : "#8b95a8", "left", kidsAt(n.m, n.s).length ? 500 : 400);
        if (l.cnt) text(` ${l.cnt}`, l.x + textW(l.txt, l.px) + 2, l.y, l.px * 0.9, rgba(colOf(n.m), 0.95), "left", 500); cx.globalAlpha = 1; }
      for (const d of L.ties) if (d.t.kind === "observed" && d.mid) { const p = toScreen(d.mid.x, d.mid.y), s = `×${d.t.count}`, px = 10 * FS, w = textW(s, px, 500) + 8;
        cx.globalAlpha = Math.min(dimOf(d.t.child), dimOf(d.t.pm)); cx.fillStyle = "rgba(8,12,22,.92)"; cx.fillRect(p.x - w / 2, p.y - px * 0.7, w, px * 1.4); text(s, p.x - w / 2 + 4, p.y, px, colOf(d.t.child), "left", 500); cx.globalAlpha = 1; }
      for (const g of L.glyphs) { if (g.quiet) continue; const p = toScreen(g.x, g.y), px = 10 * FS, under = false; cx.globalAlpha = dimOf(g.child) * 0.95;
        text(g.dag, under ? p.x : p.x + 10 * FS, p.y + (under ? 14 * FS : 0), px, DAGC, under ? "center" : "left"); cx.globalAlpha = 1; }
      for (const f of L.frames) if (f.type === "hook") { const p = toScreen(f.x, f.y), px = 10 * FS; cx.globalAlpha = dimOf(f.m); text(`↩ ${f.to}`, p.x + 4 * FS, p.y - 16 * FS * view.k, px, colOf(f.m), "left"); cx.globalAlpha = 1; }
    }
    function text(s, x, y, px, col, align = "left", wt = 400) { cx.font = font(px, wt); cx.fillStyle = col; cx.textAlign = align; cx.textBaseline = "middle"; cx.fillText(s, x, y); }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; T += dt;
      cx.setTransform(DPR, 0, 0, DPR, 0, 0); cx.fillStyle = "#05070d"; cx.fillRect(0, 0, W, H);
      const g = cx.createRadialGradient(NAVW + CW / 2, H * 0.45, 0, NAVW + CW / 2, H * 0.45, Math.max(CW, H) * 0.7); g.addColorStop(0, "rgba(40,30,80,.22)"); g.addColorStop(1, "rgba(5,7,13,0)"); cx.fillStyle = g; cx.fillRect(0, 0, W, H);
      for (const s of stars) { const tw = 0.5 + 0.5 * Math.sin(T * 0.8 + s.t); cx.fillStyle = `rgba(203,213,225,${0.12 + 0.25 * tw * s.r})`; cx.fillRect(NAVW + Math.abs(s.x) * CW, Math.abs(s.y) * H, s.r, s.r); }
      cx.setTransform(DPR * view.k, 0, 0, DPR * view.k, DPR * (NAVW + view.x), DPR * view.y);
      drawFrames(); drawEdges(); drawTies(now); drawNodes(); for (const gl of L.glyphs) drawGlyph(gl); drawTasks(now);
      cx.setTransform(DPR, 0, 0, DPR, 0, 0); drawLabels();
      if (vb && view.y + vb.y1 * view.k > CH - FOOT() + 4) { const g2 = cx.createLinearGradient(0, H - FOOT() - 50, 0, H - FOOT() + 6); g2.addColorStop(0, "rgba(5,7,13,0)"); g2.addColorStop(1, "rgba(5,7,13,.95)"); cx.fillStyle = g2; cx.fillRect(NAVW, H - FOOT() - 50, CW, 56);
        text("▾ scroll for more", NAVW + CW / 2, H - FOOT() - 6 * FS, 10.5 * FS, "#8b95a8", "center"); }
      cx.clearRect(0, 0, NAVW, H); cx.clearRect(W - RAILW, 0, RAILW, H);
      requestAnimationFrame(frame);
    }

    // ---- input: hover names, click opens a task or focuses a machine, wheel zooms, drag pans when zoomed
    function hit(sx, sy) {
      const w = toWorld(sx, sy), tol = 6 / view.k;
      for (const [ag, p] of taskPos) if (Math.hypot(p.x - w.x, p.y - w.y) < tol) return { kind: "task", o: ag };
      for (const g of L.glyphs) if (Math.hypot(g.x - w.x, g.y - w.y) < tol + 4) return { kind: "glyph", o: g };
      for (const n of L.nodes.values()) if (Math.hypot(n.x - w.x, n.y - w.y) < n.r + tol) return { kind: "node", o: n };
      for (const l of labels) if (l.node && sx >= l.x && sx <= l.x + l.w && Math.abs(sy - l.y) < l.px * 0.7) return { kind: "node", o: l.node };
      for (const l of labels) if (l.title && l.title.m && sx >= l.x && sx <= l.x + l.w && sy > l.y - l.px && sy < l.y + l.px * 2) return { kind: "frame", o: L.frames.find((f) => f.m === l.title.m && f.type !== "stalk") || { m: l.title.m } };
      for (const d of L.ties) { if (!tieShown(d)) continue; const e = tieCurve(d); for (let i = 0; i <= 30; i++) { const p = bez(e, i / 30); if (Math.hypot(p.x - w.x, p.y - w.y) < tol) return { kind: "tie", o: d }; } }
      for (const f of [...L.frames].reverse()) { if ((f.type === "hull" || f.type === "box") && w.x > f.x && w.x < f.x + f.w && w.y > f.y && w.y < f.y + f.h) return { kind: "frame", o: f };
        if (f.type === "ring" && Math.hypot(f.x - w.x, f.y - w.y) < f.r) return { kind: "frame", o: f }; }
      for (const tr of L.tracks) for (let i = 1; i < tr.pts.length; i++) if (segDist(tr.pts[i - 1], tr.pts[i], w.x, w.y) < tol) return { kind: "frame", o: tr };
      return null;
    }
    function segDist(p, q, x, y) { const dx = q.x - p.x, dy = q.y - p.y, l = dx * dx + dy * dy || 1, t = clamp(((x - p.x) * dx + (y - p.y) * dy) / l, 0, 1); return Math.hypot(p.x + t * dx - x, p.y + t * dy - y); }
    function tipHtml(h) {
      if (h.kind === "task") { const ag = h.o, oth = (byTask[ag.task] || []).filter((b) => b !== ag);
        return `<b>${esc(ag.task || ag.title)}</b> <span class="k">${esc(boardTitle[ag.task] || "")}</span><br>${esc(stName(ag.m, ag.state))} <span class="k">on ${esc(ag.m)} · ${hhmm(ag.active)}</span>` +
          (oth.length ? `<br><span class="k">also on</span> ${oth.map((b) => `${esc(b.m)} › ${esc(stName(b.m, b.state))}`).join(", ")}` : ""); }
      if (h.kind === "node") { const n = h.o, ks = kidsAt(n.m, n.s), sec = TIES.filter((t) => t.pm === n.m && t.ps === n.s && primary[t.child] !== t && t.kind === "observed"), loops = M[n.m].all.filter((t) => t.source === n.s && t.target === n.s).map((t) => t.event);
        return `<b>${esc(n.label)}</b> <span class="k">${esc(n.m)} · ${tasksAt(n.m, n.s).length} tasks${n.final ? " · final" : ""}</span>` +
          ks.map((c) => `<br>${primary[c].kind === "declared" ? "opens" : "enters"} <b style="color:${colOf(c)}">${esc(c)}</b> <span class="k">${primary[c].kind === "declared" ? `declared${primary[c].when ? `, ${esc(primary[c].when)}` : ""}` : `observed ×${primary[c].count}`}</span>`).join("") +
          sec.map((t) => `<br>enters <b style="color:${colOf(t.child)}">${esc(t.child)}</b> <span class="k">observed ×${t.count}</span>`).join("") +
          (loops.length ? `<div class="k">stays here on ${esc(loops.join(", ").toLowerCase())}</div>` : ""); }
      if (h.kind === "tie") { const t = h.o.t;
        return t.kind === "dag" ? `<b>${esc(t.dag)}</b> launches <b>${esc(t.child)}</b><br><span class="k">DAG launch · ${t.count} sessions with no task</span>` :
          `<b>${esc(stName(t.pm, t.ps))}</b> <span class="k">(${esc(t.pm)})</span> → <b>${esc(t.child)}</b><br><span class="k">${t.kind === "declared" ? "declared: the state's flow opens it" : `observed: ${t.count} session${t.count === 1 ? "" : "s"} entered it while their task sat here`}</span>`; }
      if (h.kind === "glyph") return `<b>${esc(h.o.dag)}</b> <span class="k">DAG</span><br>launches ${esc(h.o.child)}`;
      if (h.kind === "frame") return `<b>${esc(h.o.m)}</b><br><span class="k">${esc(subTitle(h.o.m))}</span>${others(h.o.m).length ? `<div class="k">dashed lines: the other states its sessions were entered from</div>` : ""}<div class="k">click to focus its ties</div>`;
      return "";
    }
    function setHover(h, sx, sy) { const same = h?.o === hover?.o; hover = h; cv.classList.toggle("hot", !!h); if (!h) { tip.style.opacity = 0; return; } if (!same) tip.innerHTML = tipHtml(h); tip.style.opacity = 1;
      const r = tip.getBoundingClientRect(); tip.style.left = `${Math.min(sx + 14, W - RAILW - r.width - 8)}px`; tip.style.top = `${Math.min(sy + 14, H - r.height - 8)}px`; }
    function openTask(ag) { pinned = ag; const all = byTask[ag.task] || [ag];
      panel.innerHTML = `<span class="x">✕</span><h2>${esc(ag.task || ag.title)}</h2><div class="k">${esc(boardTitle[ag.task] || ag.title || "")}</div>
        <table>${all.map((b) => `<tr class="mrow"><td><i style="background:${colOf(b.m)}"></i>${esc(b.m)}</td><td>${esc(stName(b.m, b.state))}</td><td style="text-align:right;color:#6b7a93">${hhmm(b.active)}</td></tr>`).join("")}</table>
        <div class="k" style="margin-top:10px">Last steps on ${esc(ag.m)}</div><table class="trace">${[...ag.trail].reverse().map((s, i) => `<tr><td>${i ? "" : "●"}</td><td>${esc(stName(ag.m, s.state))} <span class="k">${esc(s.event.toLowerCase())}</span></td><td>${hhmm(s.at)}</td></tr>`).join("")}</table>`;
      panel.classList.add("open"); panel.querySelector(".x").onclick = closePanel; }
    function openMachine(m) { focus = m; const ts = TIES.filter((t) => t.child === m || t.pm === m);
      panel.innerHTML = `<span class="x">✕</span><h2 style="color:${colOf(m)}">${esc(m)}</h2><div class="k">${esc(subTitle(m))}</div>
        <div class="k" style="margin-top:10px">Ties</div><table>${ts.map((t) => `<tr><td>${t.kind}</td><td>${t.kind === "dag" ? `${esc(t.dag)} launches ${esc(t.child)}` : `${esc(t.pm)} › ${esc(stName(t.pm, t.ps))} → ${esc(t.child)}`}</td><td style="text-align:right">${t.kind === "declared" ? "" : `×${t.count}`}</td></tr>`).join("") || `<tr><td>none in this window</td></tr>`}</table>
        <div class="k" style="margin-top:10px">States</div><table>${M[m].states.map((s) => `<tr><td>${esc(s.name)}${s.final ? " ◎" : ""}</td><td style="text-align:right">${tasksAt(m, s.id).length || ""}</td></tr>`).join("")}</table>`;
      panel.classList.add("open"); panel.querySelector(".x").onclick = closePanel; syncUrl(); }
    function closePanel() { panel.classList.remove("open"); pinned = null; focus = null; syncUrl(); }
    let drag = null;
    cv.addEventListener("mousemove", (e) => { if (drag) { view.x = drag.vx + e.clientX - drag.x; view.y = drag.vy + e.clientY - drag.y; drag.moved = true; return; } setHover(hit(e.clientX, e.clientY), e.clientX, e.clientY); });
    cv.addEventListener("mouseleave", () => setHover(null));
    cv.addEventListener("mousedown", (e) => { if (e.button === 0 && (view.k > fitK * 1.01 || overflow())) { drag = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y }; cv.classList.add("drag"); } });
    addEventListener("mouseup", () => { cv.classList.remove("drag"); setTimeout(() => (drag = null)); });
    cv.addEventListener("click", (e) => { if (drag?.moved) return; const h = hit(e.clientX, e.clientY);
      if (!h) return closePanel();
      if (h.kind === "task") return openTask(h.o);
      if (h.kind === "node") return openMachine(h.o.m === IP && kidsAt(h.o.m, h.o.s).length ? kidsAt(h.o.m, h.o.s)[0] : h.o.m);
      if (h.kind === "tie") return openMachine(h.o.t.child);
      if (h.kind === "glyph") return openMachine(h.o.child);
      if (h.kind === "frame") return openMachine(h.o.m); });
    cv.addEventListener("contextmenu", (e) => { e.preventDefault(); if (panel.classList.contains("open") || focus) closePanel(); else refit(); });
    const overflow = () => (vb.y1 - vb.y0) * view.k > CH - TOP() - FOOT() + 1;
    const scrollY = (dy) => { view.y = clamp(view.y - dy, CH - FOOT() - vb.y1 * view.k, TOP() - vb.y0 * view.k); labelKey = ""; };
    cv.addEventListener("wheel", (e) => { e.preventDefault(); if (!e.ctrlKey && view.k <= fitK * 1.01 && overflow()) return scrollY(e.deltaY); const k = clamp(view.k * Math.exp(-e.deltaY * 0.0015), fitK, fitK * 8), w = toWorld(e.clientX, e.clientY);
      view.k = k; view.x = e.clientX - NAVW - w.x * k; view.y = e.clientY - w.y * k; cv.classList.toggle("pan", k > fitK * 1.01); labelKey = ""; }, { passive: false });
    function refit() { relayout(); cv.classList.remove("pan"); }
    addEventListener("keydown", (e) => { if (e.target.tagName === "INPUT") return; const v = Object.keys(VARIANTS)[+e.key - 1];
      if (v) { e.stopPropagation(); setVariant(v); } if (e.key === "0") { e.stopPropagation(); refit(); } if (e.key === "Escape") closePanel(); }, true);
    // navigator rows for machines focus that machine here instead of opening the old level
    document.getElementById("layers").addEventListener("click", (e) => { const b = e.target.closest(".node"); const t = b?.querySelector(".t")?.textContent?.trim(); if (t && M[t]) { e.stopPropagation(); e.preventDefault(); openMachine(t); } }, true);

    // ---- the switcher and the address that reproduces the view
    function syncUrl() { const q = new URLSearchParams(location.search); q.set("mv", MV); focus ? q.set("focus", focus) : q.delete("focus"); q.delete("pick"); history.replaceState(null, "", `?${q}`); }
    function setVariant(v) { MV = v; relayout(); renderBar(); syncUrl(); }
    function setFS(p) { document.documentElement.style.fontSize = p === 100 ? "" : `${p}%`; const q = new URLSearchParams(location.search); p === 100 ? q.delete("fs") : q.set("fs", p); history.replaceState(null, "", `?${q}`); relayout(); renderBar(); }
    function renderBar() { const fs = Math.round(FS * 100);
      bar.innerHTML = Object.entries(VARIANTS).map(([k, [n]], i) => `<button data-v="${k}" class="${k === MV ? "on" : ""}">${i + 1} ${n}</button>`).join("") + `<span class="sep"></span><span style="color:#6b7a93">text</span>` +
        [100, 125, 150].map((p) => `<button data-fs="${p}" class="${p === fs ? "on" : ""}">${p}%</button>`).join("");
      bar.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => setVariant(b.dataset.v))); bar.querySelectorAll("[data-fs]").forEach((b) => (b.onclick = () => setFS(+b.dataset.fs)));
      bar.style.left = `${NAVW + CW / 2}px`; note.style.left = `${NAVW + CW / 2}px`; renderNote(); }
    const renderNote = () => (note.innerHTML = `<b>${VARIANTS[MV][0]}</b> — ${esc(VARIANTS[MV][1])}<span>▶ ${hhmm(simT)} MST · simulated</span>`);

    // ---- activity: replay what the snapshot holds, then simulate moves, sub-machine entries and DAG launches
    let simT = S.now, seq = 0;
    const lines = [];
    for (const m of Object.values(M)) for (const a of m.agents) for (const s of a.trail) lines.push({ at: s.at, html: `<b>${esc(a.task || a.id.slice(0, 8))}</b> ${esc(s.event.toLowerCase())} <em>${esc(m.name)}</em>` });
    lines.sort((a, b) => b.at - a.at); lines.length = Math.min(lines.length, 40);
    const renderFeed = () => { feed.innerHTML = lines.map((l) => `<div${l.fresh ? ' class="new"' : ""}><em>${hhmm(l.at)}</em> ${l.html}</div>`).join(""); lines.forEach((l) => (l.fresh = false)); };
    const log = (html) => { lines.unshift({ at: simT, html, fresh: true }); lines.length = Math.min(lines.length, 40); renderFeed(); renderNote(); };
    const pick = (xs) => xs[Math.floor(Math.random() * xs.length)];
    function moveTo(ag, to, event, fromKey, fromGlyph) { ag.move = { from: fromKey || key(ag.m, ag.state), fromGlyph, t0: performance.now() }; ag.state = to; ag.trail.push({ state: to, event, at: simT }); ag.trail = ag.trail.slice(-12); ag.active = simT; ag.steps = (ag.steps || 0) + 1;
      if (isFinal(ag.m, to) && ag.m !== IP) ag.doneAt = performance.now(); }
    const spare = (t) => M[t.pm].agents.filter((a) => a.state === t.ps && a.task && !a.move && !M[t.child].agents.some((b) => b.task === a.task));
    function simStep() {
      simT += 45; const r = Math.random();
      if (r < 0.22) { // a task's session enters a sub-machine from the state it sits on
        const ts = TIES.filter((t) => t.kind !== "dag" && spare(t).length), t = ts.length && pick(ts);
        if (t) { const p = pick(spare(t)), ag = { id: `sim-${++seq}`, title: p.title, model: p.model, kind: p.kind || "interactive", badges: [], task: p.task, m: t.child, state: initOf(t.child), steps: 0, trail: [], active: simT, sim: true };
          M[t.child].agents.push(ag); indexTasks(); moveTo(ag, initOf(t.child), "ENTERED", key(t.pm, t.ps)); if (t.kind === "observed") t.count++; t.flash = performance.now();
          log(`<b>${esc(p.task)}</b> entered <em>${esc(t.child)}</em> from ${esc(stName(t.pm, t.ps).toLowerCase())}`); return; } }
      if (r < 0.3) { const ts = TIES.filter((t) => t.kind === "dag" && t.child !== IP), t = ts.length && pick(ts), gl = t && L.glyphs.find((g) => g.dag === t.dag && g.child === t.child);
        if (gl) { const ag = { id: `sim-${++seq}`, title: "unattended run", model: "standard", kind: "unattended", badges: [], task: null, m: t.child, state: initOf(t.child), steps: 0, trail: [], active: simT, sim: true };
          M[t.child].agents.push(ag); moveTo(ag, initOf(t.child), "LAUNCHED", null, { x: gl.x, y: gl.y }); t.count++; t.flash = performance.now(); log(`<b>${esc(t.dag)}</b> launched <em>${esc(t.child)}</em>`); return; } }
      const pool = Object.values(M).flatMap((m) => m.agents).filter((a) => !a.move && !isFinal(a.m, a.state) && M[a.m].trans.some((t) => t.source === a.state));
      const weighted = pool.filter((a) => a.m !== IP || Math.random() < 0.35), ag = pick(weighted.length ? weighted : pool); if (!ag) return;
      const t = pick(M[ag.m].trans.filter((x) => x.source === ag.state)); moveTo(ag, t.target, t.event);
      log(`<b>${esc(ag.task || ag.id.slice(0, 8))}</b> ${esc(t.event.toLowerCase())} <em>${esc(ag.m)}</em>`);
    }
    function retire() { const now = performance.now(); for (const m of Object.values(M)) { const gone = m.agents.filter((a) => a.sim && a.doneAt && now - a.doneAt > 9000);
      if (gone.length) { if (primary[m.name]) primary[m.name].flash = now; m.agents = m.agents.filter((a) => !gone.includes(a)); indexTasks(); } } }
    setInterval(() => { if (document.hidden) return; simStep(); retire(); }, 1700);

    resize(); renderFeed(); addEventListener("resize", resize); document.fonts?.ready.then(() => { wcache.clear(); relayout(); });
    if (focus && M[focus]) openMachine(focus);
    if (P.get("pick") === "busy") { const t = Object.entries(byTask).sort((a, b) => b[1].length - a[1].length || (a[0] < b[0] ? -1 : 1))[0]; if (t) openTask(t[1].find((a) => a.m !== IP) || t[1][0]); }
    requestAnimationFrame(frame);
  }
})();
