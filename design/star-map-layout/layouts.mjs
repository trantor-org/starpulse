// Star Map layout mockup: lay each board out with each library, measure the result, and write the layouts the page draws.
//
// usage: pnpm --dir design/star-map-layout --ignore-workspace install && node design/star-map-layout/layouts.mjs [--write] [--only LIB]
//
// Every state is handed to a library as one rectangle: the cell the Board keeps for it (its footprint, its name above it, its machines'
// names either side, the gap round it), in sky units, at each type scale F the page can lay out at. The libraries are pinned to the
// board's configured tiers, left to right. `--write` writes layouts.js (window.__LAYOUTS__), which the page reads in place of running a
// library: two of the four bundles do not pass the public demo's scan, so none ships in the page.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dagre from "@dagrejs/dagre";
import ELK from "elkjs/lib/elk.bundled.js";
import { instance as graphviz } from "@viz-js/viz";
import cola from "webcola";
import "./shared.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const { boards, boardOf, pairsOf, sample } = globalThis.__BOARDS__;
const args = process.argv.slice(2), only = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;

// The Board's own sizes (starpulse/web/src/render/scene.ts: FOOT, MOONS, NAME_MAX, textW, footprint, lay).
const SUN_R = 34, TASK1 = SUN_R + 38, MOON = 18, SUB = 16, MOONS = 8, NAME_MAX = 10, NAME_ROOM = 34, GAP = 16, ZOOM_MAX = 16;
const textW = (s, size) => s.length * size * 0.56 + 6;
/** The type scale at zoom k and text size `scale` percent: sky units a pixel of text takes. */
export const typeScale = (k, scale = 100) => ((Math.max(12, Math.min(20, 0.45 * SUN_R * k)) / 13) * (scale / 100)) / k;
/** The type scales a layout is stored at; the page takes the first whose layout fits at a zoom needing no more. */
const SCALES = [0.62, 0.74, 0.88, 1.03, 1.177, 1.32, 1.472, 1.62, 1.766, 1.95, 2.2, 2.5, 2.9, 3.4, 4.0];
const RANK = 24; // sky units between two tiers' cells, the room a library routes in
/** Each state's cell at type scale F: what it takes left, right, above and below its sun's centre, and its footprint radius. */
function cells(board, F) {
  const out = {};
  for (const st of board.states) {
    let R = TASK1 + 6, reach = R;
    if (board.machines.includes(st.id)) {
      const rowH = Math.max(16 * F, 2 * MOON + 6), moonR = Math.max(TASK1 + 10 + MOON, (rowH * (MOONS / 2 + 1)) / 2);
      R = moonR + 8 + MOON;
      reach = moonR + MOON + 8 + 2 * SUB + 10 + textW("x".repeat(NAME_MAX), 10.5) * F;
    }
    // the name and the count under it are printed from 2 + 45 F above the footprint; the count is not known here, so it is given its longest
    const count = board.machines.includes(st.id) ? "0 · 0 lifecycles" : st.initial || st.final ? "00 · 00 today" : "000";
    const side = Math.max(textW(st.name, 13 * F) / 2, textW(count, 11 * F) / 2, reach), t = R + 2 + 45 * F, b = R;
    out[st.id] = { R, l: side, r: side, t, b, w: 2 * side + GAP, h: t + b + GAP, dy: (t - b) / 2 };
  }
  return out;
}
const tiersOf = (board) => {
  const of = {};
  board.tiers.forEach((t, i) => t.forEach((id) => (of[id] = i)));
  return of;
};
/** The pairs a layered library is given, each pointing down the tiers, and the same-tier pairs it cannot draw. */
function split(board) {
  const tier = tiersOf(board), given = [], same = [];
  for (const [a, b] of pairsOf(board)) {
    const ta = tier[a], tb = tier[b];
    if (ta !== undefined && ta === tb) same.push([a, b]);
    else given.push(ta !== undefined && tb !== undefined && tb < ta ? [b, a] : [a, b]);
  }
  return { tier, given, same };
}
const flat = (pts) => pts.flatMap((p) => [p.x, p.y]);
/**
 * A same-tier pair's path where the library draws none, as the Board would add it: straight between the two cells, or out round the
 * side of their column when a third state stands between them.
 */
function sameTier(a, b, pos, C, board) {
  const p = pos[a], q = pos[b], up = p.y < q.y ? [p, q, a, b] : [q, p, b, a], [hi, lo, hid, loid] = up;
  const between = board.states.some((s) => s.id !== a && s.id !== b && Math.abs(pos[s.id].x - p.x) < C[s.id].l && pos[s.id].y > hi.y && pos[s.id].y < lo.y);
  const y0 = hi.y + C[hid].b + GAP / 2, y1 = lo.y - C[loid].t - GAP / 2;
  if (!between) return { a: hid, b: loid, kind: "l", pts: [hi.x, y0, lo.x, y1], own: true };
  const x = Math.min(...board.states.filter((s) => Math.abs(pos[s.id].x - p.x) < 1).map((s) => pos[s.id].x - C[s.id].l - GAP / 2)) - RANK / 2;
  return { a: hid, b: loid, kind: "l", pts: [hi.x - C[hid].l - GAP / 2, hi.y, x, hi.y, x, lo.y, lo.x - C[loid].l - GAP / 2, lo.y], own: true };
}

const LIBS = {
  dagre: {
    name: "dagre", pkg: "@dagrejs/dagre", bundle: "@dagrejs/dagre/dist/dagre.min.js", licence: "MIT",
    pin: "no tier option: weak scaffold edges between consecutive tiers, each transition's minlen its tier distance",
    async run(board, C) {
      const { tier, given, same } = split(board), g = new dagre.graphlib.Graph().setGraph({ rankdir: "LR", nodesep: 0, ranksep: RANK, edgesep: 10, marginx: 0, marginy: 0 }).setDefaultEdgeLabel(() => ({}));
      for (const s of board.states) g.setNode(s.id, { width: C[s.id].w, height: C[s.id].h });
      const rank = [...new Set(Object.values(tier))].sort((x, y) => x - y);
      for (const [a, b] of given) g.setEdge(a, b, { minlen: tier[a] !== undefined && tier[b] !== undefined ? rank.indexOf(tier[b]) - rank.indexOf(tier[a]) : 1 });
      for (let i = 1; i < board.tiers.length; i++)
        for (const a of board.tiers[i - 1]) for (const b of board.tiers[i]) if (!g.hasEdge(a, b)) g.setEdge(a, b, { minlen: 1, weight: 0.01, scaffold: true });
      const t0 = performance.now();
      dagre.layout(g);
      const ms = performance.now() - t0, pos = Object.fromEntries(board.states.map((s) => [s.id, { x: g.node(s.id).x, y: g.node(s.id).y + C[s.id].dy }]));
      const routes = g.edges().filter((e) => !g.edge(e).scaffold).map((e) => ({ a: e.v, b: e.w, kind: "s", pts: flat(g.edge(e).points) }));
      return { pos, routes: [...routes, ...same.map(([a, b]) => sameTier(a, b, pos, C, board))], ms };
    },
  },
  graphviz: {
    name: "Graphviz dot (viz-js)", pkg: "@viz-js/viz", bundle: "@viz-js/viz/dist/viz-global.js", licence: "MIT wrapper, Graphviz EPL-2.0",
    pin: "rank=same per tier and an invisible chain between tiers",
    async run(board, C) {
      const viz = (LIBS.graphviz.viz ||= await graphviz()), { tier } = split(board), n = (id) => `"${id}"`, inch = (v) => (v / 72).toFixed(4);
      const lines = [`digraph { rankdir=LR; nodesep=0.02; ranksep=${inch(RANK)}; splines=true; node [shape=box, fixedsize=true, label=""]; edge [dir=none];`];
      for (const s of board.states) lines.push(`${n(s.id)} [width=${inch(C[s.id].w)}, height=${inch(C[s.id].h)}];`);
      for (const t of board.tiers) lines.push(`{ rank=same; ${t.map(n).join("; ")} }`);
      for (let i = 1; i < board.tiers.length; i++) lines.push(`${n(board.tiers[i - 1][0])} -> ${n(board.tiers[i][0])} [style=invis];`);
      const pairs = pairsOf(board).map(([a, b]) => (tier[a] !== undefined && tier[b] !== undefined && tier[b] < tier[a] ? [b, a] : [a, b]));
      for (const [a, b] of pairs) lines.push(`${n(a)} -> ${n(b)} [id="${a}>${b}"];`);
      lines.push("}");
      const t0 = performance.now(), out = viz.renderJSON(lines.join("\n"), { engine: "dot", yInvert: true }), ms = performance.now() - t0;
      const pos = {}, name = {};
      for (const o of out.objects ?? []) {
        name[o._gvid] = o.name;
        if (o.pos && C[o.name]) {
          const [x, y] = o.pos.split(",").map(Number);
          pos[o.name] = { x, y: y + C[o.name].dy };
        }
      }
      const routes = [];
      for (const e of out.edges ?? []) {
        if (e.style === "invis" || !e.pos) continue;
        let pts = e.pos.split(/\s+/).filter((w) => !/^[es],/.test(w)).map((w) => w.split(",").map(Number)).map(([x, y]) => ({ x, y }));
        const a = name[e.tail], b = name[e.head], d = (p, q) => Math.hypot(p.x - q.x, p.y - q.y);
        if (d(pts[0], pos[a]) > d(pts[pts.length - 1], pos[a])) pts = pts.reverse();
        routes.push({ a, b, kind: "b", pts: flat(pts) });
      }
      return { pos, routes, ms };
    },
  },
  elk: {
    name: "ELK Layered (elkjs)", pkg: "elkjs", bundle: "elkjs/lib/elk.bundled.js", licence: "EPL-2.0 OR GPL-3.0-or-later",
    pin: "partitioning: each state's partition is its tier",
    async run(board, C) {
      const elk = (LIBS.elk.elk ||= new ELK()), { tier, given, same } = split(board);
      const graph = {
        id: "root",
        layoutOptions: {
          "elk.algorithm": "layered", "elk.separateConnectedComponents": "false", "elk.direction": "RIGHT", "elk.edgeRouting": "SPLINES", "elk.partitioning.activate": "true",
          "elk.spacing.nodeNode": "0", "elk.layered.spacing.nodeNodeBetweenLayers": String(RANK), "elk.spacing.edgeNode": "10", "elk.spacing.edgeEdge": "10",
          "elk.layered.spacing.edgeNodeBetweenLayers": "10", "elk.layered.spacing.edgeEdgeBetweenLayers": "8", "elk.padding": "[top=0,left=0,bottom=0,right=0]",
        },
        children: board.states.map((s) => ({ id: s.id, width: C[s.id].w, height: C[s.id].h, ...(tier[s.id] !== undefined ? { layoutOptions: { "elk.partitioning.partition": String(tier[s.id]) } } : {}) })),
        edges: given.map(([a, b]) => ({ id: `${a}>${b}`, sources: [a], targets: [b] })),
      };
      const t0 = performance.now(), out = await elk.layout(graph), ms = performance.now() - t0;
      const pos = Object.fromEntries(out.children.map((c) => [c.id, { x: c.x + c.width / 2, y: c.y + c.height / 2 + C[c.id].dy }]));
      const routes = out.edges.flatMap((e) => (e.sections ?? []).slice(0, 1).map((s) => {
        const pts = [s.startPoint, ...(s.bendPoints ?? []), s.endPoint];
        return { a: e.sources[0], b: e.targets[0], kind: pts.length >= 4 && (pts.length - 1) % 3 === 0 ? "b" : "l", pts: flat(pts) };
      }));
      return { pos, routes: [...routes, ...same.map(([a, b]) => sameTier(a, b, pos, C, board))], ms };
    },
  },
  cola: {
    name: "WebCola", pkg: "webcola", bundle: "webcola/WebCola/cola.min.js", licence: "MIT",
    pin: "constraints: a tier's states aligned on one x, each tier's suns right of the last tier's by a footprint; rectangles kept apart",
    // The one library that can tuck: a tier need only start a footprint right of the last, so cells side by side sit at different heights
    // and overlap across. Its link length trades width for height, so it is run at three and the page takes the one that fits largest.
    variants: [80, 150, 200],
    async run(board, C, length) {
      const { tier } = split(board), ix = Object.fromEntries(board.states.map((s, i) => [s.id, i]));
      // start from the tiers as columns, a tier's states stacked, so the stress descent only has to refine them
      let x = 0;
      const start = {};
      for (const t of [...board.tiers, ...board.states.filter((s) => tier[s.id] === undefined).map((s) => [s.id])]) {
        const w = Math.max(...t.map((id) => C[id].w)), h = t.reduce((sum, id) => sum + C[id].h, 0);
        let y = -h / 2;
        for (const id of t) {
          start[id] = { x: x + w / 2, y: y + C[id].h / 2 };
          y += C[id].h;
        }
        x += w + RANK;
      }
      const nodes = board.states.map((s) => ({ ...start[s.id], width: C[s.id].w, height: C[s.id].h, id: s.id }));
      const links = pairsOf(board).map(([a, b]) => ({ source: ix[a], target: ix[b], length }));
      const cs = [];
      for (const t of board.tiers) if (t.length > 1) cs.push({ type: "alignment", axis: "x", offsets: t.map((id) => ({ node: ix[id], offset: 0 })) });
      for (let i = 1; i < board.tiers.length; i++) {
        const a = board.tiers[i - 1], b = board.tiers[i];
        for (const p of a) for (const q of b) cs.push({ axis: "x", left: ix[p], right: ix[q], gap: Math.max(C[p].R, C[q].R) });
      }
      const t0 = performance.now();
      const lay = new cola.Layout().nodes(nodes).links(links).constraints(cs).avoidOverlaps(true).handleDisconnected(false).linkDistance((l) => l.length).start(20, 40, 80, 0, false, false);
      const margin = GAP / 2;
      for (const v of nodes) v.innerBounds = v.bounds.inflate(-margin / 2);
      lay.prepareEdgeRouting(margin / 2);
      // WebCola's router throws where two rectangles it could not part still overlap; that path is then the straight line between the two
      // rectangles, drawn by the Board
      const routes = links.map((l) => {
        try {
          return { a: l.source.id, b: l.target.id, kind: "l", pts: flat(lay.routeEdge(l, 0)) };
        } catch {
          const e = cola.makeEdgeBetween(l.source.innerBounds, l.target.innerBounds, 0);
          return { a: l.source.id, b: l.target.id, kind: "l", pts: flat([e.sourceIntersection, e.targetIntersection]), own: true };
        }
      });
      const ms = performance.now() - t0, pos = Object.fromEntries(nodes.map((v) => [v.id, { x: v.x, y: v.y + C[v.id].dy }]));
      return { pos, routes, ms };
    },
  },
};

/** A layout moved so its cells and paths start at the origin, with its size. */
function framed(board, C, { pos, routes }) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const grow = (x, y) => ([x0, y0, x1, y1] = [Math.min(x0, x), Math.min(y0, y), Math.max(x1, x), Math.max(y1, y)]);
  for (const s of board.states) {
    const p = pos[s.id], c = C[s.id];
    grow(p.x - c.l - GAP / 2, p.y - c.t - GAP / 2);
    grow(p.x + c.r + GAP / 2, p.y + c.b + GAP / 2);
  }
  for (const r of routes) for (const p of sample(r.kind, r.pts)) grow(p.x, p.y);
  const at = Object.fromEntries(board.states.map((s) => [s.id, { x: pos[s.id].x - x0, y: pos[s.id].y - y0 }]));
  return { w: x1 - x0, h: y1 - y0, pos: at, routes: routes.map((r) => ({ ...r, pts: r.pts.map((v, i) => v - (i % 2 ? y0 : x0)) })) };
}

const segHitsCircle = (p, q, c, r) => {
  const dx = q.x - p.x, dy = q.y - p.y, l2 = dx * dx + dy * dy, t = l2 ? Math.max(0, Math.min(1, ((c.x - p.x) * dx + (c.y - p.y) * dy) / l2)) : 0;
  return Math.hypot(p.x + t * dx - c.x, p.y + t * dy - c.y) < r - 0.5;
};
const segX = (a, b, c, d) => {
  const o = (p, q, r) => Math.sign((q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x));
  return o(a, b, c) * o(a, b, d) < 0 && o(c, d, a) * o(c, d, b) < 0;
};
/** What a layout is measured on: its tiers, its paths, and where each state sits against the Board's middle. */
function grade(board, C, L) {
  const tier = tiersOf(board), ids = board.states.map((s) => s.id), pos = L.pos, lines = L.routes.map((r) => ({ ...r, line: sample(r.kind, r.pts) }));
  const wrong = [], splitTiers = new Set();
  for (const a of ids) for (const b of ids) {
    if (tier[a] === undefined || tier[b] === undefined) continue;
    if (tier[a] < tier[b] && !(pos[a].x < pos[b].x - 1)) wrong.push(`${a} not left of ${b}`);
    if (a < b && tier[a] === tier[b] && Math.abs(pos[a].x - pos[b].x) > 1) splitTiers.add(tier[a]);
  }
  let through = 0, cross = 0;
  for (const r of lines) if (ids.some((id) => id !== r.a && id !== r.b && r.line.some((p, i) => i && segHitsCircle(r.line[i - 1], p, pos[id], C[id].R)))) through++;
  for (let i = 0; i < lines.length; i++) for (let j = i + 1; j < lines.length; j++) {
    const a = lines[i].line, c = lines[j].line;
    let x = false;
    for (let m = 1; m < a.length && !x; m++) for (let n = 1; n < c.length && !x; n++) x = segX(a[m - 1], a[m], c[n - 1], c[n]);
    if (x) cross++;
  }
  const ys = ids.map((id) => pos[id].y), mid = (Math.min(...ys) + Math.max(...ys)) / 2;
  const side = Object.fromEntries(ids.map((id) => [id, pos[id].y < mid - SUN_R / 2 ? "high" : pos[id].y > mid + SUN_R / 2 ? "low" : "mid"]));
  const pairs = pairsOf(board).length, own = L.routes.filter((r) => r.own).length;
  return { tiers: wrong.length ? `order broken (${wrong[0]}${wrong.length > 1 ? `, +${wrong.length - 1}` : ""})` : splitTiers.size ? `order kept, ${splitTiers.size} tier(s) split across columns` : "kept",
    drawn: L.routes.length - own, own, pairs, through, cross, side };
}
/**
 * The layout the page draws in a W x H canvas, and the sun's radius on screen: of the stored type scales, the first whose layout (the
 * variant that fits largest) fits at a zoom needing no more. mock.js holds the same rule.
 */
function sunPx(byScale, W, H, scale = 100) {
  for (let i = 0; i < SCALES.length; i++) {
    const ks = byScale[i].map((L) => Math.min((0.94 * W) / L.w, (0.94 * H) / L.h, ZOOM_MAX)), k = Math.max(...ks);
    if (typeScale(k, scale) <= SCALES[i] + 1e-3 || i === SCALES.length - 1) return { k, px: SUN_R * k, F: SCALES[i], L: byScale[i][ks.indexOf(k)] };
  }
}

const VIEWPORTS = [[1366, 768], [1920, 1080], [2560, 1440], [3440, 1440]], PANEL = 500; // the canvas is the window less the page's two rails
const keys = [...Object.keys(boards), ...boards.base.states.map((s) => `base~${s.id}`)]; // every board, and the demo board with each state switched off
const sets = {}, report = [];
for (const [lib, def] of Object.entries(LIBS)) {
  if (only && lib !== only) continue;
  const size = fs.statSync(path.join(HERE, "node_modules", def.bundle)).size, version = JSON.parse(fs.readFileSync(path.join(HERE, "node_modules", def.pkg, "package.json"), "utf8")).version;
  console.log(`\n== ${def.name} ${version}: bundle ${(size / 1024).toFixed(0)} KB, ${def.licence}; tiers pinned by ${def.pin}`);
  const grades = {};
  for (const key of keys) {
    const board = boardOf(key), byScale = [], times = [];
    for (const F of SCALES) {
      const C = cells(board, F), at = [];
      for (const v of def.variants ?? [0]) {
        const raw = await def.run(board, C, v);
        times.push(raw.ms);
        at.push({ ...framed(board, C, raw), C });
      }
      byScale.push(at);
    }
    // graded as the page draws it at 1920x1080
    const ref = sunPx(byScale, 1920 - PANEL, 1080).L, g = grade(board, ref.C, ref);
    grades[key] = g;
    const suns = VIEWPORTS.map(([w, h]) => `${w}x${h} ${sunPx(byScale, w - PANEL, h).px.toFixed(1)}`).join(", ");
    times.sort((a, b) => a - b);
    console.log(`${key.padEnd(22)} tiers ${g.tiers}; box ${ref.w.toFixed(0)}x${ref.h.toFixed(0)}; sun px ${suns}; paths ${g.drawn}/${g.pairs} by the library${g.own ? ` (+${g.own} by the Board)` : ""}, ${g.through} through a state, ${g.cross} pairs crossing; ${times[times.length >> 1].toFixed(1)} ms`);
    (sets[key] ||= {})[lib] = byScale.map((at) => at.map((L) => ({
      w: Math.ceil(L.w), h: Math.ceil(L.h), p: board.states.flatMap((s) => [Math.round(L.pos[s.id].x), Math.round(L.pos[s.id].y)]),
      e: L.routes.map((r) => [r.a, r.b, r.kind + (r.own ? "o" : ""), ...r.pts.map((v) => Math.round(v))]),
    })));
  }
  // stability: against the whole demo board, which of the states left change side of the Board's middle or their order down a tier when one is switched off
  const moved = boards.base.states.map((s) => {
    const g = grades[`base~${s.id}`], left = boards.base.states.map((q) => q.id).filter((id) => id !== s.id);
    return { off: s.id, ids: left.filter((id) => grades.base.side[id] !== g.side[id]) };
  });
  console.log(`stability: states changing side when one is switched off: ${moved.map((m) => `${m.off} ${m.ids.length}${m.ids.length ? ` (${m.ids.join(", ")})` : ""}`).join("; ")}; total ${moved.reduce((n, m) => n + m.ids.length, 0)}`);
  report.push({ lib, version, size });
}
if (args.includes("--write")) {
  const out = `// Generated by layouts.mjs: each board laid out by each library at each type scale. Do not edit.\nglobalThis.__LAYOUTS__ = ${JSON.stringify({ scales: SCALES, libs: Object.fromEntries(Object.entries(LIBS).map(([k, d]) => [k, { name: d.name, licence: d.licence, pin: d.pin, ...report.find((r) => r.lib === k) }])), sets })};\n`;
  fs.writeFileSync(path.join(HERE, "layouts.js"), out);
  console.log(`\nwrote layouts.js: ${(out.length / 1024).toFixed(0)} KB`);
}
