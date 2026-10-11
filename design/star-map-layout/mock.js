// Design mockup layer (the Star Map Board laid out by a layout library), never part of the page. The page above is a scrubbed capture
// of the real StarPulse page, built from a source copy (star-map-layout-src.patch) that lets a script hand the Board its states' places
// and its paths. This layer picks a board (shared.js), writes it over the capture's board machine, and hands the Board the layout one of
// four libraries gave that board (layouts.js, computed by layouts.mjs): the library's places for the states, pinned to the configured
// tiers left to right, and its route for each pair of states. The Board still draws everything: suns, rings, moons, names, tasks, and
// the last leg of each path from the cell's edge to the state's rim, and it redraws every path as one smooth curve that goes no further
// over a name or into a state than the library's own line does. It runs before the page's module.
//   ?lib=shipped|dagre|graphviz|elk|cola   who lays the Board out (shipped: the page's own placement and route search)
//   ?board=base|third-in-tier|two-more-tiers|fourteen|unlisted|three   the board drawn
//   ?off=<state>   the demo board with one state switched off (the chips set it)
//   ?fs=100|125|150   the Admin text size
//   ?paths=1   every path redrawn bright over the Board, to read the routes   ?bar=1   the strip opened to every control
(() => {
  const q = new URLSearchParams(location.search), FX = window.__FLOW_FIXTURE__, B = globalThis.__BOARDS__, LY = globalThis.__LAYOUTS__;
  const LIBS = { shipped: "Shipped Board", dagre: "dagre", graphviz: "Graphviz dot", elk: "ELK Layered", cola: "WebCola" };
  const NAMES = { base: "Demo board", "third-in-tier": "Third state in a tier", "two-more-tiers": "Two more tiers", fourteen: "14 states", unlisted: "State in no tier", three: "3 states" };
  const lib = LIBS[q.get("lib")] ? q.get("lib") : "shipped", name = B.boards[q.get("board")] ? q.get("board") : "base";
  const off = name === "base" && B.boards.base.states.some((s) => s.id === q.get("off")) ? q.get("off") : "";
  const key = off ? `${name}~${off}` : name, board = B.boardOf(key), fs = [100, 125, 150].includes(Number(q.get("fs"))) ? Number(q.get("fs")) : 100;
  const bright = q.get("paths") === "1", folded = q.get("bar") !== "1";
  try {
    const k = "fv.admin.prefs", p = JSON.parse(localStorage.getItem(k) || "{}");
    p.scale = fs;
    localStorage.setItem(k, JSON.stringify(p));
  } catch { /* storage off: the page keeps 100% */ }

  // the board, written over the capture's: its states, tiers and transitions, the capture's tasks kept where their state still stands and
  // a few given to each added state
  const flow = FX?.flows.find((f) => f.name === "board");
  if (flow) {
    const m = flow.machine, ids = new Set(board.states.map((s) => s.id)), was = new Set(m.states.map((s) => s.id));
    const event = (a, b) => m.transitions.find((t) => t.source === a && t.target === b)?.event ?? `${a}_to_${b}`.toUpperCase();
    const transitions = board.transitions.map(([a, b]) => ({ source: a, target: b, event: event(a, b) }));
    Object.assign(m, {
      states: board.states.map((s) => ({ ...s })), tiers: board.tiers, mainLine: board.mainLine, transitions,
      subflows: (m.subflows ?? []).filter((s) => ids.has(s.state)),
    });
    const spare = flow.agents.filter((a) => a.state === "waiting"), added = board.states.filter((s) => !was.has(s.id) && !s.initial);
    flow.agents = flow.agents.filter((a) => ids.has(a.state));
    added.forEach((s, i) => spare.slice(i * 5, i * 5 + 5).forEach((a, j) => flow.agents.push({ ...a, id: `DEMO-9${i}${j}`, state: s.id, dependencies: [] })));
    for (const [id, t] of Object.entries(FX.settled ?? {})) if (!ids.has(t.state)) delete FX.settled[id];
    for (const id of Object.keys(FX.history ?? {})) FX.history[id] = FX.history[id].filter((e) => (e.from == null || ids.has(e.from)) && ids.has(e.to));
  }

  // a library's layout for the canvas: of the type scales it was laid out at, the first whose layout (the variant that fits largest) fits
  // at a zoom needing no more, centred in the sky (layouts.mjs holds the same rule)
  const sets = lib === "shipped" ? null : LY.sets[key]?.[lib];
  if (sets) {
    let memo = null;
    window.__LAYOUT__ = ({ W, H, F, kmax }) => {
      if (memo?.at === `${W}x${H}`) return memo.out;
      let k = 0, L = null;
      for (let i = 0; i < LY.scales.length && !L; i++) {
        const ks = sets[i].map((l) => Math.min((0.94 * W) / l.w, (0.94 * H) / l.h, kmax));
        k = Math.max(...ks);
        if (F(k) <= LY.scales[i] + 1e-3 || i === LY.scales.length - 1) L = sets[i][ks.indexOf(k)];
      }
      const ox = ((0.94 * W) / k - L.w) / 2, oy = ((0.94 * H) / k - L.h) / 2, ps = {}, routes = {};
      board.states.forEach((s, i) => (ps[s.id] = { x: L.p[2 * i] + ox, y: L.p[2 * i + 1] + oy }));
      for (const [a, b, kind, ...flat] of L.e) routes[`${a}>${b}`] = B.sample(kind[0], flat).map((p) => ({ x: p.x + ox, y: p.y + oy }));
      memo = { at: `${W}x${H}`, out: { k, ps, routes } };
      return memo.out;
    };
  }

  // What the page drew, measured off its own probe, on screen: the same reading for the shipped Board and every library. measure.py calls it.
  const hit = (a, b, c, d) => {
    const o = (p, q, r) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x));
    return o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0;
  };
  const near = (p, q, c) => {
    const dx = q.x - p.x, dy = q.y - p.y, l = dx * dx + dy * dy, t = l ? Math.max(0, Math.min(1, ((c.x - p.x) * dx + (c.y - p.y) * dy) / l)) : 0;
    return Math.hypot(p.x + t * dx - c.x, p.y + t * dy - c.y);
  };
  let last = null, lastAt = 0;
  window.__GRADE__ = () => {
    if (last && performance.now() - lastAt < 400) return last; // measure.py asks every frame until the page is ready
    const pr = window.flowProbe?.();
    if (!pr?.ready || !pr.states?.length) return null;
    const st = Object.fromEntries(pr.states.map((s) => [s.id, s])), seen = new Set(), lines = [];
    for (const p of pr.paths) {
      if (seen.has(`${p.target}>${p.source}`) || seen.has(`${p.source}>${p.target}`)) continue; // a pair joined both ways is one path
      seen.add(`${p.source}>${p.target}`);
      lines.push(p);
    }
    const tier = {};
    board.tiers.forEach((t, i) => t.forEach((id) => (tier[id] = i)));
    let order = 0, joined = 0, through = 0, named = 0, cross = 0;
    for (const a of pr.states) for (const b of pr.states) if (tier[a.id] < tier[b.id] && !(a.x < b.x - 1)) order++;
    for (const l of lines) {
      const a = st[l.source], b = st[l.target], p0 = l.pts[0], p1 = l.pts[l.pts.length - 1];
      if (Math.abs(Math.hypot(p0.x - a.x, p0.y - a.y) - a.edge) < 3 && Math.abs(Math.hypot(p1.x - b.x, p1.y - b.y) - b.edge) < 3) joined++;
      if (pr.states.some((s) => s !== a && s !== b && l.pts.some((p, i) => i && near(l.pts[i - 1], p, s) < s.r - 1))) through++;
      if (pr.names.some((n) => l.pts.some((p) => p.x > n.x0 + 1 && p.x < n.x1 - 1 && p.y > n.y0 + 1 && p.y < n.y1 - 1))) named++;
    }
    // each path in runs of 16 pieces with the box round each run, so two paths are compared piece by piece only where their runs' boxes meet
    const runs = lines.map((l) => {
      const out = [];
      for (let i = 0; i + 1 < l.pts.length; i += 16) {
        const part = l.pts.slice(i, i + 17), xs = part.map((p) => p.x), ys = part.map((p) => p.y);
        out.push({ part, x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) });
      }
      return out;
    });
    const crosses = (A, C) => A.some((a) => C.some((c) => a.x0 <= c.x1 && c.x0 <= a.x1 && a.y0 <= c.y1 && c.y0 <= a.y1 && a.part.some((p, m) => m && c.part.some((r, n) => n && hit(a.part[m - 1], p, c.part[n - 1], r)))));
    for (let i = 0; i < lines.length; i++) for (let j = i + 1; j < lines.length; j++) if (crosses(runs[i], runs[j])) cross++;
    const ys = pr.states.map((s) => s.y), mid = (Math.min(...ys) + Math.max(...ys)) / 2, sun = 34 * pr.fit;
    const side = Object.fromEntries(pr.states.map((s) => [s.id, s.y < mid - sun / 2 ? "high" : s.y > mid + sun / 2 ? "low" : "mid"]));
    const xs = pr.states.flatMap((s) => [s.x - s.r, s.x + s.r]), box = { w: Math.max(...xs) - Math.min(...xs), h: Math.max(...pr.states.map((s) => s.y + s.r)) - Math.min(...pr.states.map((s) => s.y - s.r)) };
    lastAt = performance.now();
    return last = { lib, board: key, fs, canvas: pr.canvas, sun, states: pr.states.length, order, pairs: board ? B.pairsOf(board).length : 0, paths: lines.length, joined, through, named, cross, side, box };
  };

  // the strip: one address per library, board and switched-off state
  const css = document.createElement("style");
  css.textContent = `
    #lay { position: fixed; z-index: 50; left: calc(var(--nav, 250px) + 12px); bottom: 4px; max-width: calc(100vw - var(--nav, 250px) - var(--rail, 250px) - 24px); box-sizing: border-box;
      padding: 3px 8px; border-radius: 6px; background: color-mix(in srgb, var(--glass) 88%, transparent); border: 1px solid color-mix(in srgb, var(--slate) 22%, transparent);
      font-size: calc(11.5px * var(--fs)); color: var(--ink-2); line-height: 1.5; }
    #lay .row { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: center; }
    #lay .row + .row { margin-top: 4px; }
    #lay .lb { color: var(--muted); min-width: calc(46px * var(--fs)); }
    #lay a { padding: 0 8px; border-radius: 4px; color: var(--ink-3); text-decoration: none; border: 1px solid color-mix(in srgb, var(--slate) 22%, transparent); white-space: nowrap; }
    #lay a.on { background: color-mix(in srgb, var(--agent) 24%, transparent); color: var(--ink); border-color: color-mix(in srgb, var(--agent) 55%, transparent); }
    #lay a.off { color: var(--muted); text-decoration: line-through; }
    #lay a:hover, #lay a:focus-visible { background: color-mix(in srgb, var(--agent) 12%, transparent); outline: none; }
    #lay .read { color: var(--ink-3); font-variant-numeric: tabular-nums; }
    #lay .read b { font-weight: 500; color: var(--ink); }
    #lay .read .bad { color: var(--fail-text); }
    #lay.folded .row { display: none; }
    #lay.folded .row.fold { display: flex; }
    #lay-paths { position: fixed; z-index: 40; pointer-events: none; }
    #lay-paths polyline { fill: none; stroke: var(--agent-text); stroke-width: 1.3; stroke-opacity: 0.8; }`;
  document.head.append(css);
  const href = (over) => {
    const p = new URLSearchParams({ lib, board: name, ...(off ? { off } : {}), ...(fs !== 100 ? { fs: String(fs) } : {}), ...(bright ? { paths: "1" } : {}), ...(folded ? {} : { bar: "1" }), ...over });
    for (const [k, v] of [...p]) if (!v) p.delete(k);
    return `${location.pathname}?${p}`;
  };
  const link = (label, over, on, cls = "") => `<a href="${href(over)}" class="${on ? "on" : ""} ${cls}">${label}</a>`;
  const meta = LY.libs[lib], el = document.createElement("div");
  el.id = "lay";
  el.className = folded ? "folded" : "";
  // folded, the strip is one row at the foot of the Board, inside the margin the Board leaves round its states
  el.innerHTML = `
    <div class="row fold"><span class="lb">Layout</span>${Object.entries(LIBS).map(([k, v]) => link(v, { lib: k }, k === lib)).join("")}
      ${link("bright paths", { paths: bright ? "" : "1" }, bright)}${link(folded ? "more controls" : "fewer controls", { bar: folded ? "1" : "" }, false)}
      ${folded ? `<span class="lb">${NAMES[name]}${off ? ` less ${off}` : ""}${fs !== 100 ? ` · ${fs}%` : ""}</span>` : ""}</div>
    <div class="row"><span class="lb">Board</span>${Object.entries(NAMES).map(([k, v]) => link(v, { board: k, off: "" }, k === name)).join("")}</div>
    ${name === "base" ? `<div class="row"><span class="lb">States</span>${B.boards.base.states.map((s) => link(s.name, { off: s.id === off ? "" : s.id }, false, s.id === off ? "off" : "")).join("")}<span class="lb">click one to switch it off</span></div>` : ""}
    <div class="row"><span class="lb">Text</span>${[100, 125, 150].map((v) => link(`${v}%`, { fs: v === 100 ? "" : String(v) }, v === fs)).join("")}</div>
    <div class="row"><span class="read" id="lay-read"></span></div>`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.id = "lay-paths";
  addEventListener("DOMContentLoaded", () => document.body.append(el, ...(bright ? [svg] : [])));
  const bad = (n, text) => (n ? `<span class="bad">${n} ${text}</span>` : `0 ${text}`);
  setInterval(() => {
    const g = window.__GRADE__(), out = document.getElementById("lay-read"), cv = document.querySelector("canvas");
    if (!g || !out) return;
    if (bright && cv) {
      const r = cv.getBoundingClientRect();
      Object.assign(svg.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
      svg.innerHTML = window.flowProbe().paths.map((l) => `<polyline points="${l.pts.map((v) => `${v.x.toFixed(1)},${v.y.toFixed(1)}`).join(" ")}"/>`).join("");
    }
    out.innerHTML = `sun <b>${g.sun.toFixed(1)} px</b> · ${g.joined}/${g.pairs} paths joined rim to rim · ${bad(g.through, "through a state")} · ${bad(g.named, "over a name")} · ${g.cross} pairs crossing · ${
      bad(g.order, "tier pairs out of order")}${meta ? ` · ${meta.name} ${meta.version}, ${(meta.size / 1024).toFixed(0)} KB, ${meta.licence}` : " · no library: the page's own placement and route search"}`;
  }, 1000);
})();
