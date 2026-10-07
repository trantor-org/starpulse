// DAG constellations mockup: the Board with its DAGs drawn as constellations instead of one hangar sun.
// Every option is a query parameter so each state has its own address:
//   glyph=classic|radiant  one=glint|dim|asterism|cluster  place=regions|systems|zodiac  tied=path|satellite
//   n=51|150|400 (live DAGs, then synthetic ones for scale)  fs=1|1.25|1.5  s=<scene>  dag=<name>  domain=<name>
"use strict";

const LIVE = window.LIVE;
const P = new URLSearchParams(location.search);
const SCENES = {
  board: {},
  radiant: { glyph: "radiant" },
  fan: { dag: "apply-on-merge", zoom: 1 },
  chain: { dag: "graph-refresh", zoom: 1 },
  run: { dag: "apply-on-merge", zoom: 1, run: 1 },
  systems: { place: "systems" },
  domain: { place: "systems", domain: "Delivery & CI" },
  zodiac: { place: "zodiac" },
  satellite: { tied: "satellite" },
  scale: { n: 400 },
  "scale-systems": { n: 400, place: "systems" },
  sheet: { sheet: 1 },
  refuse: { dag: "memory-reindex", zoom: 1, hold: "gpu-1" },
};
const scene = SCENES[P.get("s")] ? P.get("s") : "board";
const pick = (k, d) => P.get(k) ?? SCENES[scene][k] ?? d;
const opt = {
  glyph: pick("glyph", "classic"),
  one: pick("one", "glint"),
  place: pick("place", "regions"),
  tied: pick("tied", "path"),
  n: +pick("n", 51),
  fs: +pick("fs", 1),
  sheet: !!+pick("sheet", 0),
};
document.documentElement.style.setProperty("--fs", opt.fs);

// ---------- seeded randomness ----------
function hash(s) { let h = 2166136261; for (const c of s) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function rng(seed) { let a = typeof seed === "string" ? hash(seed) : seed >>> 0; return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }

// ---------- data: live DAGs, then synthetic ones for the scale test ----------
const DOMAIN_COLOR = { "Delivery & CI": "#38bdf8", "Board": "#a78bfa", "Agent jobs & evals": "#f472b6", "Retrieval & tags": "#34d399", "Host ops & backups": "#fbbf24" };
const EXTRA_DOMAINS = [["Home & media", "#fb923c"], ["Security", "#f87171"], ["Data pipelines", "#22d3ee"], ["Observability", "#a3e635"], ["Network", "#60a5fa"], ["Finance", "#e879f9"], ["Docs & knowledge", "#2dd4bf"], ["Experiments", "#c4b5fd"]];
EXTRA_DOMAINS.forEach(([d, c]) => (DOMAIN_COLOR[d] = c));
const dags = LIVE.dags.map((d) => ({ ...d, steps: d.steps.map(([name, depends, kind, status]) => ({ name, depends, kind, status })), synthetic: false }));
const domains = [...LIVE.domains];
// s=refuse: a scheduled run already holds this pool's only slot, so Run now meets the server's refusal
const held = LIVE.pools.find((p) => p.name === pick("hold", "")); if (held) held.running = held.cap;
if (opt.n > dags.length) {
  const r = rng(7 + opt.n);
  const verbs = ["sync", "reindex", "backup", "scan", "rotate", "export", "prune", "audit", "probe", "compact", "ingest", "render", "retrain", "verify", "mirror", "report"];
  const nouns = ["photos", "certs", "dns", "ledger", "invoices", "media-library", "vectors", "firmware", "logs", "metrics", "wiki", "feeds", "snapshots", "zigbee", "vpn-peers", "camera-clips", "secrets", "sbom", "notes", "calendar"];
  const extra = Math.min(EXTRA_DOMAINS.length, Math.round((opt.n - 51) / 45));
  for (let i = 0; i < extra; i++) domains.push(EXTRA_DOMAINS[i][0]);
  const used = new Set(dags.map((d) => d.name));
  while (dags.length < opt.n) {
    let name = `${verbs[(r() * verbs.length) | 0]}-${nouns[(r() * nouns.length) | 0]}`; for (let k = 2; used.has(name); k++) name = name.replace(/-\d+$/, "") + `-${k}`; used.add(name);
    const domain = r() < 0.7 && extra ? domains[5 + ((r() * extra) | 0)] : domains[(r() * 5) | 0];
    const shape = r(); const steps = [];
    const add = (n, deps) => steps.push({ name: n, depends: deps, kind: r() < 0.2 ? "agent" : "code", status: "succeeded" });
    if (shape < 0.55) add("run", []);
    else if (shape < 0.78) { const k = 2 + ((r() * 5) | 0); for (let j = 0; j < k; j++) add(`s${j}`, j ? [`s${j - 1}`] : []); }
    else if (shape < 0.92) { const k = 3 + ((r() * 6) | 0); add("plan", []); for (let j = 0; j < k; j++) add(`b${j}`, ["plan"]); add("merge", steps.slice(1).map((s) => s.name)); }
    else { add("a", []); add("b", ["a"]); add("c", ["a"]); add("d", ["b", "c"]); add("e", ["d"]); }
    const st = r(); const status = st < 0.04 ? "failed" : st < 0.07 ? "not_started" : "succeeded";
    if (status === "failed") steps[(r() * steps.length) | 0].status = "failed";
    if (status === "not_started") steps.forEach((s) => (s.status = "not_started"));
    dags.push({ name, domain, status, pool: "default", runSafe: r() < 0.5, steps, synthetic: true });
  }
}
const byName = new Map(dags.map((d) => [d.name, d]));
// The DAGs tied to the Board (they write a Board event, are cued by one, or launch a state's machine) and the state each relates to.
const TIES = LIVE.ties;
const RELATES = { "board-autopilot": "ready", "board-dependency-reconciliation": "waiting", "main-follow": "done", "apply-on-merge": "done", "graph-refresh": "done", "backlog-sweep": "completed", "dependency-update-investigation": "in_progress" };
const isTied = (d) => !!TIES[d.name];

// ---------- the Board ----------
const STATES = {
  new: { name: "New", x: -594, y: 0, r: 48, c: "#64748b", n: 162, lab: "up", sub: "162 today" },
  ready: { name: "Ready", x: -465, y: 0, r: 36, c: "#60a5fa", n: 30, lab: "down" },
  waiting: { name: "Waiting", x: -336, y: -158, r: 50, c: "#facc15", n: 58, lab: "up" },
  in_progress: { name: "In Progress", x: -5, y: 0, r: 38, c: "#818cf8", n: 28, lab: "up", sub: "28 · 8 lifecycles" },
  needs_attention: { name: "Needs Attention", x: -336, y: 158, r: 22, c: "#94a3b8", n: 5, lab: "down" },
  review: { name: "Review", x: 249, y: 0, r: 20, c: "#c084fc", n: 1, lab: "down" },
  done: { name: "Done", x: 442, y: 0, r: 75, c: "#2dd4bf", n: 113, lab: "up" },
  completed: { name: "Completed", x: 571, y: -257, r: 44, c: "hole", n: 51, lab: "up", sub: "51 today" },
  archived: { name: "Archived", x: 571, y: 257, r: 14, c: "hole", n: 3, lab: "up", sub: "3 today" },
};
const MOONS = [["auditing-docs", -1, -33], ["authoring-skills", -1, -12], ["investigating-dependency-updates", -1, 10], ["running-skill-evals", -1, 32],
  ["in-progress › PR Opened", 1, -33], ["auditing-infrastructure", 1, -12], ["realigning-stale-docs", 1, 10], ["graph-traversal", 1, 32]];
const PAIRS = LIVE.pairs.map(([a, b, ev]) => ({ a, b, ev }));
PAIRS.forEach((p) => { p.both = PAIRS.some((q) => q.a === p.b && q.b === p.a); });
function pathGeom(p) {
  const A = STATES[p.a], B = STATES[p.b]; const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2; const dx = B.x - A.x, dy = B.y - A.y; const L = Math.hypot(dx, dy) || 1;
  const nx = -dy / L, ny = dx / L; const bow = p.both ? 0.16 * L : 0.06 * L; const cx = mx + nx * bow, cy = my + ny * bow;
  return { A, B, cx, cy, mid: { x: (A.x + 2 * cx + B.x) / 4, y: (A.y + 2 * cy + B.y) / 4 }, nx, ny };
}

// ---------- glyph layouts (local coordinates, centred) ----------
function depthOf(steps) {
  const m = new Map(steps.map((s) => [s.name, s])); const memo = new Map();
  const d = (s) => { if (memo.has(s.name)) return memo.get(s.name); memo.set(s.name, 0); const v = s.depends.length ? 1 + Math.max(...s.depends.map((x) => (m.has(x) ? d(m.get(x)) : 0))) : 0; memo.set(s.name, v); return v; };
  steps.forEach(d); return memo;
}
const glyphCache = new Map();
function glyph(dag) {
  const key = `${dag.name}|${opt.glyph}|${dag.steps.length}`; if (glyphCache.has(key)) return glyphCache.get(key);
  const steps = dag.steps.length ? dag.steps : [{ name: dag.name, depends: [], status: dag.status }];
  const r = rng(dag.name); const depth = depthOf(steps); const idx = new Map(steps.map((s, i) => [s.name, i]));
  const pts = steps.map(() => ({ x: 0, y: 0 })); const edges = []; let core = null;
  steps.forEach((s, i) => s.depends.forEach((d) => idx.has(d) && edges.push([idx.get(d), i])));
  if (steps.length === 1) { /* one-step: a single star, drawn by the one-step treatment */ }
  else if (opt.glyph === "classic") {
    // layered: depth along an axis, siblings spread across it in their parents' order, then turned, bent and jittered so no two read alike
    const a0 = r() * Math.PI * 2; const L = 13, Wd = 8.5; const layers = []; const off = new Array(steps.length).fill(0);
    steps.forEach((s, i) => (layers[depth.get(s.name)] ||= []).push(i));
    layers.forEach((ids) => {
      const bary = (i) => { const ps = steps[i].depends.filter((d) => idx.has(d)).map((d) => off[idx.get(d)]); return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : 0; };
      ids.sort((a, b) => bary(a) - bary(b));
      const groups = new Map(); ids.forEach((i) => { const k = bary(i).toFixed(2); (groups.get(k) || groups.set(k, []).get(k)).push(i); });
      for (const [k, g] of groups) g.forEach((i, j) => (off[i] = +k + (j - (g.length - 1) / 2) * Wd));
      const sorted = [...ids].sort((a, b) => off[a] - off[b]); for (let j = 1; j < sorted.length; j++) if (off[sorted[j]] - off[sorted[j - 1]] < Wd) off[sorted[j]] = off[sorted[j - 1]] + Wd;
    });
    const bend = (r() - 0.5) * 0.012;
    steps.forEach((s, i) => { const d = depth.get(s.name); const u = d * L + (r() - 0.5) * 5, v = off[i] + bend * u * u + (r() - 0.5) * 4;
      pts[i] = { x: Math.cos(a0) * u - Math.sin(a0) * v, y: Math.sin(a0) * u + Math.cos(a0) * v }; });
  } else {
    const a0 = r() * Math.PI * 2; core = { x: 0, y: 0 };
    steps.forEach((s, i) => { const a = a0 + (Math.PI * 2 * i) / steps.length; const len = 10 + 7 * depth.get(s.name) + r() * 3; pts[i] = { x: Math.cos(a) * len, y: Math.sin(a) * len }; });
  }
  // centre on the bounding circle
  let cx = 0, cy = 0; if (!core) { pts.forEach((p) => { cx += p.x; cy += p.y; }); cx /= pts.length; cy /= pts.length; pts.forEach((p) => { p.x -= cx; p.y -= cy; }); }
  const rad = Math.max(5, ...pts.map((p) => Math.hypot(p.x, p.y))) + 4;
  const g = { steps, pts, edges, core, r: steps.length === 1 ? (opt.one === "dim" ? 4 : 7) : rad };
  glyphCache.set(key, g); return g;
}

// ---------- placement ----------
let levelStack = [{ kind: "board" }];
let items = []; // {kind:'dag'|'cluster'|'system'|'text'|'region', ...} in world coordinates for the open level
let deco = []; // region hazes, zodiac rings and asterism lines
const BOARD_EXCL = { rx: 820, ry: 440 };
function inBoard(x, y, r) { return ((x) / (BOARD_EXCL.rx + r)) ** 2 + ((y) / (BOARD_EXCL.ry + r)) ** 2 < 1; }
function clearOfStates(x, y, r) { return Object.values(STATES).every((s) => Math.hypot(s.x - x, s.y - y) > s.r + r + 46); }

function unitsFor(list, domain) {
  // one-step DAGs as a cluster unit when the treatment says so; every other DAG is its own unit
  const singles = list.filter((d) => d.steps.length <= 1), multi = list.filter((d) => d.steps.length > 1);
  const units = multi.map((d) => ({ kind: "dag", dag: d, r: glyph(d).r }));
  if (opt.one === "cluster" && singles.length > 1) {
    const sp = 11; const members = singles.map((d, i) => { const a = i * 2.39996, rr = sp * 0.62 * Math.sqrt(i + 0.5); return { dag: d, dx: Math.cos(a) * rr, dy: Math.sin(a) * rr }; });
    units.push({ kind: "cluster", domain, members, r: sp * 0.62 * Math.sqrt(singles.length) + 9 });
  } else singles.forEach((d) => units.push({ kind: "dag", dag: d, r: glyph(d).r }));
  return units.sort((a, b) => b.r - a.r);
}
const PAD = () => 16 + 10 * opt.fs;
function packSector(units, placed, sector, order) {
  // sector: {a0, a1, rx0, ry0, center?:{x,y}, disc?:true}
  const out = [];
  // spatial hash over what is already placed, so a 400-DAG sky packs in milliseconds rather than minutes
  const G = 48, cells = new Map(); let maxR = 0; const key = (i, j) => i * 100003 + j;
  const add = (p) => { maxR = Math.max(maxR, p.r); const k = key(Math.floor(p.x / G), Math.floor(p.y / G)); (cells.get(k) || cells.set(k, []).get(k)).push(p); };
  const free = (x, y, r) => { const R = r + maxR + PAD(); for (let i = Math.floor((x - R) / G); i <= Math.floor((x + R) / G); i++) for (let j = Math.floor((y - R) / G); j <= Math.floor((y + R) / G); j++) for (const p of cells.get(key(i, j)) || []) if (Math.hypot(p.x - x, p.y - y) <= p.r + r + PAD()) return false; return true; };
  placed.forEach(add);
  for (const u of units) {
    let ok = null;
    for (let k = 0; k < 400 && !ok; k++) {
      const grow = k * 7; const samples = 9 + k;
      const cand = [];
      for (let j = 0; j < samples; j++) {
        const t = order === "angular" ? j / Math.max(1, samples - 1) : 0.5 + (j % 2 ? 1 : -1) * Math.ceil(j / 2) / samples;
        if (t < 0 || t > 1) continue; cand.push(t);
      }
      if (order === "scatter") { const rr = rng(u.kind + (u.dag?.name || u.domain) + k); const key = new Map(cand.map((t) => [t, Math.abs(t - 0.5) + rr() * 0.22])); cand.sort((a, b) => key.get(a) - key.get(b)); }
      for (const t of cand) {
        const a = sector.a0 + (sector.a1 - sector.a0) * t;
        const x = (sector.cx || 0) + Math.cos(a) * (sector.rx0 + grow + u.r), y = (sector.cy || 0) + Math.sin(a) * (sector.ry0 + grow + u.r);
        if (sector.board && (inBoard(x, y, u.r) || !clearOfStates(x, y, u.r))) continue;
        const margin = (u.r + PAD()) / Math.max(60, Math.hypot(x, y));
        if (sector.a1 - sector.a0 < Math.PI * 1.99 && (a < sector.a0 + margin * 0.6 || a > sector.a1 - margin * 0.6)) continue;
        if (free(x, y, u.r)) { ok = { x, y }; break; }
      }
    }
    const it = { ...u, x: ok.x, y: ok.y }; placed.push(it); add(it); out.push(it);
  }
  return out;
}
function placeTied(placed) {
  const tied = dags.filter(isTied);
  if (opt.tied === "path") {
    const groups = new Map();
    for (const d of tied) {
      if (d.name === "dependency-update-investigation") { const g = glyph(d); const it = { kind: "dag", dag: d, r: g.r, x: STATES.in_progress.x - 318 - g.r, y: 10, anchor: { x: STATES.in_progress.x - 43, y: 10 }, tied: true }; placed.push(it); items.push(it); continue; }
      const cnt = new Map(); TIES[d.name].forEach((t) => { if (t.source !== t.target) { const k = `${t.source}>${t.target}`; cnt.set(k, (cnt.get(k) || 0) + 1); } });
      const best = [...cnt].sort((a, b) => b[1] - a[1])[0][0]; (groups.get(best) || groups.set(best, []).get(best)).push(d);
    }
    for (const [k, list] of groups) {
      const [a, b] = k.split(">"); const p = PAIRS.find((q) => q.a === a && q.b === b) || { a, b, both: false }; const G = pathGeom(p);
      let nx = G.nx, ny = G.ny; if (ny > 0 || (ny === 0 && nx > 0)) { nx = -nx; ny = -ny; } // stack upward
      let off = 16;
      for (const d of list) { const g = glyph(d); off += g.r; let x = G.mid.x + nx * off, y = G.mid.y + ny * off;
        for (let tries = 0; tries < 30 && placed.some((q) => Math.hypot(q.x - x, q.y - y) < q.r + g.r + 10); tries++) { off += 8; x = G.mid.x + nx * off; y = G.mid.y + ny * off; }
        const it = { kind: "dag", dag: d, r: g.r, x, y, anchor: G.mid, path: p, tied: true }; placed.push(it); items.push(it); off += g.r + 12; }
    }
  } else {
    const per = new Map(); tied.forEach((d) => (per.get(RELATES[d.name]) || per.set(RELATES[d.name], []).get(RELATES[d.name])).push(d));
    for (const [sid, list] of per) {
      const S = STATES[sid]; let ang = -Math.PI / 2 - (sid === "in_progress" ? 0 : 0.0); let side = 1; let cursor = 0;
      list.forEach((d, i) => {
        const g = glyph(d); const R = S.r + 34 + g.r + (sid === "in_progress" ? 150 : 0);
        const a = sid === "in_progress" ? Math.PI / 2 + 0.0 : ang + side * cursor; side = -side; if (side > 0) cursor += (2 * g.r + 16) / R;
        const it = { kind: "dag", dag: d, r: g.r, x: S.x + Math.cos(a) * R, y: S.y + Math.sin(a) * R, anchor: S, state: sid, tied: true }; placed.push(it); items.push(it);
      });
    }
  }
}
function boardPlaced() {
  const placed = Object.entries(STATES).map(([k, s]) => ({ x: s.x, y: s.y, r: s.r + 30 }));
  placed.push({ x: -170, y: 0, r: 120 }, { x: 160, y: 0, r: 110 }); // In Progress moon labels
  return placed;
}
function layoutLevel() {
  items = []; deco = []; glyphCache.clear();
  const top = levelStack[levelStack.length - 1];
  if (opt.sheet) return layoutSheet();
  if (top.kind === "domain") return layoutDomain(top.domain);
  const placed = boardPlaced(); placeTied(placed);
  const free = dags.filter((d) => !isTied(d));
  const byDomain = domains.map((dn) => [dn, free.filter((d) => d.domain === dn)]).filter(([, l]) => l.length);
  if (opt.place === "systems") {
    const n = byDomain.length; const RX = 900, RY = 500;
    byDomain.forEach(([dn, list], i) => {
      const a = -Math.PI / 2 + (Math.PI * 2 * i) / n + 0.0; const r = 26 + 5.2 * Math.sqrt(list.length);
      let x = Math.cos(a) * (RX + r), y = Math.sin(a) * (RY + r);
      const it = { kind: "system", domain: dn, list, r, x, y }; placed.push(it); items.push(it);
    });
  } else {
    const total = byDomain.reduce((s, [, l]) => s + l.reduce((q, d) => q + glyph(d).r ** 2, 0) + 400, 0);
    let a = -Math.PI * 0.86; const span = Math.PI * 2;
    for (const [dn, list] of byDomain) {
      const w = (list.reduce((q, d) => q + glyph(d).r ** 2, 0) + 400) / total; const a1 = a + span * w;
      const sector = { a0: a, a1, rx0: BOARD_EXCL.rx - 60, ry0: BOARD_EXCL.ry - 60, board: true };
      const units = unitsFor(list, dn); const got = packSector(units, placed, sector, opt.place === "zodiac" ? "angular" : "scatter");
      got.forEach((g) => { g.domain = dn; items.push(g); });
      deco.push({ kind: opt.place === "zodiac" ? "sign" : "region", domain: dn, a0: a, a1, members: got, n: list.length });
      a = a1;
    }
  }
  if (opt.one === "asterism") asterisms();
}
function layoutDomain(dn) {
  const list = dags.filter((d) => d.domain === dn && !isTied(d)); const placed = [];
  const got = packSector(unitsFor(list, dn), placed, { a0: -Math.PI, a1: Math.PI, rx0: 0, ry0: 0 }, "scatter");
  got.forEach((g) => { g.domain = dn; items.push(g); });
  deco.push({ kind: "region", domain: dn, a0: -Math.PI, a1: Math.PI, members: got, n: list.length, solo: true });
  if (opt.one === "asterism") asterisms();
}
function asterisms() {
  // join each domain's one-step stars by a minimum spanning tree: faint, dashed, so it never reads as a dependency
  const byD = new Map(); items.filter((i) => i.kind === "dag" && !i.tied && i.dag.steps.length <= 1).forEach((i) => (byD.get(i.domain) || byD.set(i.domain, []).get(i.domain)).push(i));
  for (const [, pts] of byD) {
    const inT = [pts[0]], rest = pts.slice(1);
    while (rest.length) { let best = null; for (const a of inT) for (const b of rest) { const d = Math.hypot(a.x - b.x, a.y - b.y); if (!best || d < best.d) best = { a, b, d }; } if (best.d > 260) { inT.push(best.b); rest.splice(rest.indexOf(best.b), 1); continue; } deco.push({ kind: "aster", a: best.a, b: best.b }); inT.push(best.b); rest.splice(rest.indexOf(best.b), 1); }
  }
}
function layoutSheet() {
  const rows = ["apply-on-merge", "graph-refresh", "deliver", "alert-investigation", "cleanup-workspace", "session-transcript-stats"];
  const colX = [-330, 0, 330]; let y = -300;
  items.push({ kind: "text", x: colX[1], y: y - 70, text: "Classic constellation", big: true }, { kind: "text", x: colX[2], y: y - 70, text: "Radiant star", big: true });
  const saved = opt.glyph;
  rows.forEach((n) => {
    const d = byName.get(n); const gl = ["classic", "radiant"].map((gs) => { opt.glyph = gs; glyphCache.clear(); return glyph(d); });
    const half = Math.max(...gl.map((g) => g.r)) * SHEET_K; y += half;
    items.push({ kind: "text", x: colX[0], y, text: n, sub: `${d.steps.length} steps · ${d.domain}` });
    gl.forEach((g, ci) => items.push({ kind: "dag", dag: d, r: g.r * SHEET_K, x: colX[ci + 1], y, g, fixedGlyph: true, noLabel: true }));
    y += half + 26;
  });
  opt.glyph = saved; glyphCache.clear();
  y += 90; items.push({ kind: "text", x: colX[0], y, text: "One-step DAGs", sub: "35 of 51 live DAGs" });
  const ones = ["healthcheck", "rag-metrics", "postgres-restore-verify", "tag-analytics", "mutation-sweep"];
  const treat = [["glint", "Glint star"], ["dim", "Dim star"], ["asterism", "Domain asterism"], ["cluster", "Open cluster"]];
  treat.forEach(([t, label], k) => {
    const cx = -120 + k * 200; items.push({ kind: "text", x: cx, y: y - 62, text: label });
    ones.forEach((n, j) => { const d = byName.get(n); const a = j * 2.39996, rr = t === "cluster" ? 7 * Math.sqrt(j + 0.5) : 26 + 8 * (j % 2);
      const p = t === "cluster" ? { x: cx + Math.cos(a) * rr * 1.6, y: y + 10 + Math.sin(a) * rr * 1.6 } : { x: cx - 72 + j * 36, y: y + 10 + (j % 2 ? -20 : 18) };
      items.push({ kind: "dag", dag: d, r: 6, x: p.x, y: p.y, one: t, noLabel: true }); });
    if (t === "asterism") for (let j = 1; j < ones.length; j++) deco.push({ kind: "aster", a: items[items.length - ones.length + j - 1], b: items[items.length - ones.length + j] });
    if (t === "cluster") deco.push({ kind: "haze", x: cx, y: y + 10, r: 44, c: "#38bdf8" });
  });
}

// ---------- runs (simulated scheduler) ----------
function renderPools() {
  document.getElementById("pools").innerHTML = LIVE.pools.map((p) => `<div class="pool"><div class="r"><span>${p.name}</span><span style="color:${p.running ? "#fbbf24" : ""}">${p.running}/${p.cap}</span></div><div class="bar"><i style="width:${(100 * p.running) / p.cap}%"></i></div></div>`).join("");
}
const runs = new Map(); // dag name -> {state: Map(step -> 'running'|'succeeded'|'failed'), until: Map}
const rings = []; // {x,y,r0,c,t0,dur}
const recent = [];
function startRun(d, reason) {
  if (runs.has(d.name)) return false;
  const st = new Map(d.steps.map((s) => [s.name, "not_started"])); runs.set(d.name, { st, until: new Map() });
  const pl = LIVE.pools.find((p) => p.name === d.pool); if (pl) { pl.running++; renderPools(); }
  pushRecent(`dagu/${d.name}`, "running", "run", reason); return true;
}
function tickRuns(now) {
  for (const [name, run] of runs) {
    const d = byName.get(name); let all = true;
    for (const s of d.steps) {
      const v = run.st.get(s.name);
      if (v === "not_started" && s.depends.every((x) => !run.st.has(x) || run.st.get(x) === "succeeded")) { run.st.set(s.name, "running"); run.until.set(s.name, now + 900 + Math.random() * 2200); ringStep(d, s.name, "#fbbf24"); }
      else if (v === "running" && now > run.until.get(s.name)) run.st.set(s.name, "succeeded");
      if (run.st.get(s.name) !== "succeeded") all = false;
    }
    if (all) { runs.delete(name); const pl = LIVE.pools.find((p) => p.name === d.pool); if (pl) { pl.running = Math.max(0, pl.running - 1); renderPools(); } d.status = "succeeded"; d.steps.forEach((s) => (s.status = "succeeded")); d.finishedAt = new Date().toISOString(); ringDag(d, "#34d399"); pushRecent(`dagu/${name}`, "succeeded", "ok"); if (panelDag === d) renderPanel(); }
  }
}
function stepStatus(d, s) { const r = runs.get(d.name); return r ? (r.st.get(s.name) === "not_started" ? "pending" : r.st.get(s.name)) : s.status || d.status; }
function itemOf(d) { return items.find((i) => i.dag === d) || items.find((i) => i.kind === "cluster" && i.members.some((m) => m.dag === d)) || items.find((i) => i.kind === "system" && i.list.includes(d)); }
function ringStep(d, step, c) { const it = itemOf(d); if (!it) return; let x = it.x, y = it.y; if (it.kind === "dag") { const g = it.g || glyph(d); const i = g.steps.findIndex((s) => s.name === step); if (i >= 0) { x += g.pts[i].x; y += g.pts[i].y; } } rings.push({ x, y, r0: 3, c, t0: performance.now(), dur: 1100, grow: 14 }); }
function ringDag(d, c) { const it = itemOf(d); if (it) rings.push({ x: it.x, y: it.y, r0: (it.kind === "dag" ? it.r : 8), c, t0: performance.now(), dur: 1800, grow: 26 }); }

// ---------- camera ----------
const cv = document.getElementById("sky"); const ctx = cv.getContext("2d");
let W = 0, H = 0, DPR = 1; const NAV = 250, RAIL = 250;
let cam = { s: 1, x: 0, y: 0 }, fitCam = cam, anim = null;
function resize() { DPR = window.devicePixelRatio || 1; W = innerWidth; H = innerHeight; cv.width = W * DPR; cv.height = H * DPR; cv.style.width = W + "px"; cv.style.height = H + "px"; }
function contentBox() {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const add = (x, y, r) => { x0 = Math.min(x0, x - r); y0 = Math.min(y0, y - r); x1 = Math.max(x1, x + r); y1 = Math.max(y1, y + r); };
  const top = levelStack[levelStack.length - 1];
  if (top.kind === "board" && !opt.sheet) Object.values(STATES).forEach((s) => add(s.x, s.y, s.r + 40));
  items.forEach((i) => add(i.x, i.y, (i.r || 0) + (i.kind === "text" ? 120 : 14)));
  return { x0, y0, x1, y1 };
}
function computeFit() {
  const b = contentBox(); const aw = W - NAV - RAIL - 80, ah = H - 150; const cap = levelStack[levelStack.length - 1].kind === "domain" ? 3 : 1.6; const s = Math.min(aw / (b.x1 - b.x0), ah / (b.y1 - b.y0), cap);
  return { s, x: NAV + 40 + aw / 2 - s * (b.x0 + b.x1) / 2, y: 40 + ah / 2 - s * (b.y0 + b.y1) / 2 };
}
const toScreen = (x, y) => [cam.x + x * cam.s, cam.y + y * cam.s];
const toWorld = (sx, sy) => [(sx - cam.x) / cam.s, (sy - cam.y) / cam.s];
function flyTo(target, dur = 450) { anim = { from: { ...cam }, to: target, t0: performance.now(), dur }; }
function zoomOn(x, y, r) { const s = Math.min(fitCam.s * 8, Math.max(fitCam.s * 1.6, 130 / Math.max(r, 8))); const cx = NAV + (W - NAV - RAIL) / 2 - (panelDag ? 160 : 0); flyTo({ s, x: cx - x * s, y: H / 2 - y * s }, 520); }

// ---------- drawing ----------
const SHEET_K = 2.6;
const COL = { succeeded: "#e6fff7", ok: "#34d399", failed: "#fb7185", running: "#fbbf24", pending: "#fbbf24", not_started: "#8b97ad", aborted: "#8b97ad" };
const stars = (() => { const r = rng(3); return Array.from({ length: 260 }, () => ({ x: r(), y: r(), a: 0.15 + r() * 0.45, s: r() < 0.08 ? 1.4 : 0.8 })); })();
let hover = null, hoverStep = null, hiTarget = null, panelDag = null;
function font(px, w = 400) { return `${w} ${px * opt.fs}px Inter, system-ui, sans-serif`; }
function drawStar(x, y, rad, color, glow, alpha = 1) {
  ctx.globalAlpha = alpha; if (glow) { const g = ctx.createRadialGradient(x, y, 0, x, y, rad * 4); g.addColorStop(0, glow + "66"); g.addColorStop(1, glow + "00"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, rad * 4, 0, 7); ctx.fill(); }
  ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, rad, 0, 7); ctx.fill(); ctx.globalAlpha = 1;
}
function hollow(x, y, rad, alpha = 1) { ctx.globalAlpha = alpha; ctx.strokeStyle = "#8b97ad"; ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, rad, 0, 7); ctx.stroke(); ctx.globalAlpha = 1; }
function stepPaint(x, y, status, rad, t, lit) {
  if (status === "not_started" || status === "aborted") return hollow(x, y, rad, lit ? 1 : 0.7);
  if (status === "pending") return hollow(x, y, rad, 0.8);
  if (status === "running") { const tw = 0.6 + 0.4 * Math.sin(t / 160 + x); return drawStar(x, y, rad * (1 + 0.25 * tw), "#fde68a", "#fbbf24", 1); }
  if (status === "failed") return drawStar(x, y, rad, "#fecdd3", "#fb7185", 1);
  drawStar(x, y, rad, lit ? "#ffffff" : "#d9f7ee", "#34d399", lit ? 1 : 0.92);
}
function oneStep(x, y, d, mode, s, t, lit) {
  const status = stepStatus(d, d.steps[0] || { status: d.status });
  if (mode === "dim") { if (status === "running") return stepPaint(x, y, status, 2.2, t, lit); ctx.globalAlpha = lit ? 1 : 0.55; ctx.fillStyle = status === "failed" ? "#fb7185" : status === "not_started" || status === "aborted" ? "#64748b" : "#b8c4d6"; ctx.beginPath(); ctx.arc(x, y, lit ? 2.4 : 1.7, 0, 7); ctx.fill(); ctx.globalAlpha = 1; return; }
  if (mode === "glint") {
    const c = status === "failed" ? "#fb7185" : status === "running" ? "#fbbf24" : status === "not_started" || status === "aborted" ? "#8b97ad" : "#9ff3dc";
    const L = (lit ? 9 : 7) * Math.min(1.6, Math.max(0.8, s)); ctx.strokeStyle = c; ctx.globalAlpha = lit ? 0.9 : 0.55; ctx.lineWidth = 0.8;
    ctx.beginPath(); ctx.moveTo(x - L, y); ctx.lineTo(x + L, y); ctx.moveTo(x, y - L); ctx.lineTo(x, y + L); ctx.stroke(); ctx.globalAlpha = 1;
    if (status === "not_started" || status === "aborted") return hollow(x, y, 2.6);
    return stepPaint(x, y, status, 2.6, t, lit);
  }
  stepPaint(x, y, status, 2.3, t, lit);
}
function drawGlyph(it, t, lit) {
  const d = it.dag; const [sx, sy] = toScreen(it.x, it.y); const z = cam.s;
  const mode = it.one || opt.one;
  if (d.steps.length <= 1) return oneStep(sx, sy, d, mode === "cluster" || mode === "asterism" ? "plain" : mode, z, t, lit);
  const g = it.g || glyph(d);
  if (it.r * z < 5 && !lit && !it.fixedGlyph) { // too small to read its shape: one star in its latest run's colour
    const st = runs.has(d.name) ? "running" : d.status; return stepPaint(sx, sy, st === "succeeded" ? "succeeded" : st, 2.2, t, false);
  }
  const k = z * (it.fixedGlyph ? SHEET_K : 1);
  const P = g.pts.map((p) => [sx + p.x * k, sy + p.y * k]);
  if (g.core) {
    for (let i = 0; i < P.length; i++) { const grd = ctx.createLinearGradient(sx, sy, P[i][0], P[i][1]); grd.addColorStop(0, lit ? "rgba(230,255,247,.75)" : "rgba(200,240,230,.5)"); grd.addColorStop(1, "rgba(200,240,230,.05)"); ctx.strokeStyle = grd; ctx.lineWidth = lit ? 1.3 : 1; ctx.beginPath(); ctx.moveTo(sx, sy); ctx.lineTo(P[i][0], P[i][1]); ctx.stroke(); }
    const st = runs.has(d.name) ? "running" : d.status;
    drawStar(sx, sy, Math.max(2.6, 3.4 * Math.min(1.5, z)), st === "failed" ? "#fecdd3" : st === "running" ? "#fde68a" : "#ffffff", st === "failed" ? "#fb7185" : st === "running" ? "#fbbf24" : "#34d399", 1);
  } else {
    ctx.strokeStyle = lit ? "rgba(203,213,225,.55)" : "rgba(148,163,184,.30)"; ctx.lineWidth = lit ? 1.1 : 0.8;
    ctx.beginPath(); g.edges.forEach(([a, b]) => { ctx.moveTo(P[a][0], P[a][1]); ctx.lineTo(P[b][0], P[b][1]); }); ctx.stroke();
  }
  const rad = Math.max(1.6, Math.min(3.2, 1.9 * Math.sqrt(k)));
  g.steps.forEach((s, i) => stepPaint(P[i][0], P[i][1], stepStatus(d, s), (s.kind === "agent" ? 1.25 : 1) * (g.core ? rad * 0.8 : rad), t, lit || (hoverStep && hoverStep.dag === d && hoverStep.i === i)));
}
function labelFor(it) { return it.kind === "dag" ? it.dag.name : it.kind === "cluster" ? `${it.members.length} one-step DAGs` : it.kind === "system" ? it.domain : ""; }
function draw(t) {
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  const bg = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.7); bg.addColorStop(0, "#0c1324"); bg.addColorStop(1, "#05070d"); ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);
  stars.forEach((s) => { ctx.globalAlpha = s.a; ctx.fillStyle = "#94a3b8"; ctx.fillRect(s.x * W, s.y * H, s.s, s.s); }); ctx.globalAlpha = 1;
  const top = levelStack[levelStack.length - 1];
  const labels = []; // [priority, x, y, text, color, align, font]
  // region hazes and zodiac signs
  for (const dc of deco) {
    if (dc.kind === "region" || dc.kind === "sign") {
      if (!dc.members.length) continue; let cx = 0, cy = 0; dc.members.forEach((m) => { cx += m.x; cy += m.y; }); cx /= dc.members.length; cy /= dc.members.length;
      const R = Math.max(...dc.members.map((m) => Math.hypot(m.x - cx, m.y - cy) + m.r)) + 30; const [x, y] = toScreen(cx, cy); const c = DOMAIN_COLOR[dc.domain] || "#94a3b8";
      if (dc.kind === "region") { const g = ctx.createRadialGradient(x, y, 0, x, y, R * cam.s); g.addColorStop(0, c + "1e"); g.addColorStop(1, c + "00"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R * cam.s, 0, 7); ctx.fill(); }
      // the region's name sits on its outer edge, away from the Board
      let lx = x, ly = y - R * cam.s - 4;
      if (!dc.solo) { const L = Math.hypot(cx, cy) || 1, ux = cx / L, uy = cy / L; const ext = Math.max(...dc.members.map((m) => m.x * ux + m.y * uy + m.r)) + 22; [lx, ly] = toScreen(ux * ext, uy * ext); }
      ctx.font = font(10, 500); const lw = ctx.measureText(dc.domain).width / 2 + 40;
      const clx = Math.min(Math.max(lx, NAV + lw + 8), W - RAIL - lw - 8);
      // pushed back in by a panel edge, the name would sit on its own stars: put it above or below the cluster instead
      if (Math.abs(clx - lx) > 4) ly = cy < 0 ? toScreen(0, Math.min(...dc.members.map((m) => m.y - m.r)))[1] - 16 : toScreen(0, Math.max(...dc.members.map((m) => m.y + m.r)))[1] + 30;
      lx = clx; ly = Math.min(Math.max(ly, 30), H - 90);
      // zoomed in, the stars carry their own names; a region name pinned to the viewport edge would only overprint the chrome
      if (cam.s <= fitCam.s * 1.4) labels.push([0.5, lx, ly, `${dc.domain.toUpperCase()}  ·  ${dc.n}`, c + "dd", "center", font(10, 500), 0]);
    } else if (dc.kind === "aster") {
      const [ax, ay] = toScreen(dc.a.x, dc.a.y), [bx, by] = toScreen(dc.b.x, dc.b.y); ctx.setLineDash([2, 4]); ctx.strokeStyle = "rgba(148,163,184,.22)"; ctx.lineWidth = 0.8; ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke(); ctx.setLineDash([]);
    } else if (dc.kind === "haze") { const [x, y] = toScreen(dc.x, dc.y); const g = ctx.createRadialGradient(x, y, 0, x, y, dc.r * cam.s); g.addColorStop(0, dc.c + "22"); g.addColorStop(1, dc.c + "00"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, dc.r * cam.s, 0, 7); ctx.fill(); }
  }
  if (opt.place === "zodiac" && top.kind === "board" && !opt.sheet) {
    // the ecliptic: two faint rings bounding the band, with a tick at each sign boundary
    const signs = deco.filter((d) => d.kind === "sign"); const rIn = Math.min(...items.filter((i) => !i.tied && i.kind !== "system").map((i) => Math.hypot(i.x / BOARD_EXCL.rx, i.y / BOARD_EXCL.ry))) || 1;
    ctx.strokeStyle = "rgba(148,163,184,.10)"; ctx.lineWidth = 1; const [cx, cy] = toScreen(0, 0);
    for (const k of [0.93, 1.0]) { ctx.beginPath(); ctx.ellipse(cx, cy, BOARD_EXCL.rx * rIn * k * cam.s, BOARD_EXCL.ry * rIn * k * cam.s, 0, 0, 7); ctx.stroke(); }
    signs.forEach((sg) => { const a = sg.a0; const [x0, y0] = toScreen(Math.cos(a) * BOARD_EXCL.rx * rIn * 0.93, Math.sin(a) * BOARD_EXCL.ry * rIn * 0.93); const [x1, y1] = toScreen(Math.cos(a) * BOARD_EXCL.rx * rIn * 1.0, Math.sin(a) * BOARD_EXCL.ry * rIn * 1.0); ctx.strokeStyle = "rgba(148,163,184,.14)"; ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke(); });
  }
  if (top.kind === "board" && !opt.sheet) drawBoard(t, labels);
  // hovered tied DAG: its tether and the path it writes
  const hv = hover && hover.kind === "dag" ? hover : null;
  if (hv && hv.tied && hv.anchor) { const [ax, ay] = toScreen(hv.anchor.x, hv.anchor.y), [bx, by] = toScreen(hv.x, hv.y); ctx.setLineDash([3, 4]); ctx.strokeStyle = "rgba(167,139,250,.7)"; ctx.lineWidth = 1.2; ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(ax, ay); ctx.stroke(); ctx.setLineDash([]); }
  // items
  for (const it of items) {
    const lit = hover === it || hiTarget === it || (panelDag && it.dag === panelDag);
    const [x, y] = toScreen(it.x, it.y);
    if (x < NAV - 200 || x > W + 200 || y < -200 || y > H + 200) continue;
    if (it.kind === "text") { labels.push([10, x, y - (it.big ? 0 : 6), it.text, it.big ? "#dbe4f3" : "#c3cde0", it.big ? "center" : "center", font(it.big ? 13 : 12, 500), 1]); if (it.sub) labels.push([10, x, y + 12, it.sub, "#6b7a93", "center", font(10.5), 1]); continue; }
    if (it.kind === "system") { drawSystem(it, t, lit, labels); continue; }
    if (it.kind === "cluster") {
      const R = it.r * cam.s; const g = ctx.createRadialGradient(x, y, 0, x, y, R * 1.3); const c = DOMAIN_COLOR[it.domain] || "#94a3b8"; g.addColorStop(0, c + (lit ? "30" : "1c")); g.addColorStop(1, c + "00"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R * 1.3, 0, 7); ctx.fill();
      it.members.forEach((m) => { const mx = x + m.dx * cam.s, my = y + m.dy * cam.s; const ml = lit || (hoverStep && hoverStep.dag === m.dag) || panelDag === m.dag; stepPaint(mx, my, stepStatus(m.dag, m.dag.steps[0] || {}), Math.max(1.3, Math.min(2.6, 1.6 * Math.sqrt(cam.s))), t, ml);
        if (cam.s * 11 > 60 * opt.fs || (hoverStep && hoverStep.dag === m.dag)) labels.push([hoverStep && hoverStep.dag === m.dag ? 0 : 6, mx, my + 12 * opt.fs, m.dag.name, "#8b97ad", "center", font(10), 0]); });
      labels.push([lit ? 0 : 4, x, y + R + 14 * opt.fs, `${it.members.length} one-step`, lit ? "#dbe4f3" : "#7c89a1", "center", font(10.5), 0]);
      continue;
    }
    drawGlyph(it, t, lit);
    if (!it.noLabel) { const pri = lit ? 0 : it.tied ? 2 : it.dag.steps.length > 1 ? 3 : 5; const gl = it.dag.steps.length > 1 && it.r * cam.s >= 5 ? (it.g || glyph(it.dag)) : null; const below = gl ? Math.max(...gl.pts.map((q) => q.y)) * cam.s + 6 : Math.max(it.r * cam.s, 4); labels.push([pri, x, y + below + 12 * opt.fs, it.dag.name, lit ? "#ffffff" : it.tied ? "#a8b3c8" : "#7c89a1", "center", font(10.5), 0]); }
  }
  // step tooltip-on-canvas when zoomed into a constellation
  // rings
  for (let i = rings.length - 1; i >= 0; i--) { const r = rings[i]; const p = (t - r.t0) / r.dur; if (p >= 1) { rings.splice(i, 1); continue; } const [x, y] = toScreen(r.x, r.y); ctx.strokeStyle = r.c; ctx.globalAlpha = 1 - p; ctx.lineWidth = 1.4; ctx.beginPath(); ctx.arc(x, y, r.r0 * Math.min(cam.s, 3) + r.grow * p, 0, 7); ctx.stroke(); ctx.globalAlpha = 1; }
  // labels with greedy collision culling, priority first
  labels.sort((a, b) => a[0] - b[0]); const taken = [];
  const pr = panel.classList.contains("on") ? panel.getBoundingClientRect() : null; if (pr) taken.push([pr.left, pr.top, pr.right, pr.bottom]);
  for (let [pri, x, y, text, color, align, f, alwaysish] of labels) {
    ctx.font = f; const w = ctx.measureText(text).width, h = 12 * opt.fs; let x0 = align === "center" ? x - w / 2 : align === "right" ? x - w : x;
    // a name that must show slides inside the sky rather than vanish under a side panel
    if (alwaysish) { const dx = Math.max(0, NAV + 6 - x0) - Math.max(0, x0 + w - (W - RAIL - 6)); x += dx; x0 += dx; }
    const box = [x0 - 3, y - h, x0 + w + 3, y + 3];
    if (pri > 0 && !alwaysish && taken.some((b) => !(box[2] < b[0] || box[0] > b[2] || box[3] < b[1] || box[1] > b[3]))) continue;
    if (pri > 0 && !alwaysish && (box[0] < NAV + 4 || box[2] > W - RAIL - 4 || box[1] < 4 || box[3] > H - 4)) continue;
    taken.push(box); ctx.fillStyle = color; ctx.textAlign = align; ctx.fillText(text, x, y);
  }
  ctx.textAlign = "left";
}
function drawSystem(it, t, lit, labels) {
  const [x, y] = toScreen(it.x, it.y); const R = it.r * cam.s; const c = DOMAIN_COLOR[it.domain] || "#94a3b8";
  const g = ctx.createRadialGradient(x, y, 0, x, y, R * 1.25); g.addColorStop(0, c + (lit ? "3a" : "22")); g.addColorStop(0.7, c + "0c"); g.addColorStop(1, c + "00"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R * 1.25, 0, 7); ctx.fill();
  ctx.strokeStyle = c + (lit ? "aa" : "55"); ctx.setLineDash([2, 4]); ctx.lineWidth = 1; ctx.beginPath(); ctx.arc(x, y, R, 0, 7); ctx.stroke(); ctx.setLineDash([]);
  it.list.forEach((d, i) => { const a = i * 2.39996 + hash(it.domain) % 7, rr = R * 0.82 * Math.sqrt((i + 0.5) / it.list.length); const st = runs.has(d.name) ? "running" : d.status;
    const px = x + Math.cos(a) * rr, py = y + Math.sin(a) * rr; const size = d.steps.length > 1 ? 1.9 : 1.2;
    if (st === "running") stepPaint(px, py, "running", 2, t, false); else if (st === "failed") drawStar(px, py, size + 0.4, "#fb7185", "#fb7185"); else if (st === "not_started" || st === "aborted") hollow(px, py, size); else { ctx.globalAlpha = d.steps.length > 1 ? 0.95 : 0.6; ctx.fillStyle = "#d9f7ee"; ctx.beginPath(); ctx.arc(px, py, size, 0, 7); ctx.fill(); ctx.globalAlpha = 1; } });
  const failed = it.list.filter((d) => d.status === "failed").length, running = it.list.filter((d) => runs.has(d.name)).length;
  labels.push([1, x, y + R + 16 * opt.fs, it.domain, lit ? "#ffffff" : "#c3cde0", "center", font(12, 500), 1]);
  labels.push([1, x, y + R + 30 * opt.fs, `${it.list.length} DAGs${running ? ` · ${running} running` : ""}${failed ? ` · ${failed} failed` : ""}`, failed ? "#fda4af" : "#6b7a93", "center", font(10.5), 1]);
}
function drawBoard(t, labels) {
  // paths
  const hv = hover && hover.kind === "dag" && hover.tied ? hover.dag : null;
  const litPairs = hv ? new Set((TIES[hv.name] || []).map((x) => `${x.source}>${x.target}`)) : new Set();
  for (const p of PAIRS) { const G = pathGeom(p); const [ax, ay] = toScreen(G.A.x, G.A.y), [bx, by] = toScreen(G.B.x, G.B.y), [cx, cy] = toScreen(G.cx, G.cy);
    const lit = litPairs.has(`${p.a}>${p.b}`); ctx.strokeStyle = lit ? "rgba(196,181,253,.85)" : "rgba(148,163,184,.11)"; ctx.lineWidth = lit ? 1.8 : 1; ctx.setLineDash(lit ? [] : [3, 5]); ctx.beginPath(); ctx.moveTo(ax, ay); ctx.quadraticCurveTo(cx, cy, bx, by); ctx.stroke(); }
  ctx.setLineDash([]);
  // states
  for (const [id, s] of Object.entries(STATES)) {
    const [x, y] = toScreen(s.x, s.y); const R = s.r * cam.s;
    if (s.c === "hole") { const g = ctx.createRadialGradient(x, y, R * 0.6, x, y, R * 1.25); g.addColorStop(0, "#000"); g.addColorStop(0.75, "rgba(45,212,191,.35)"); g.addColorStop(1, "rgba(45,212,191,0)"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R * 1.25, 0, 7); ctx.fill(); ctx.fillStyle = "#000"; ctx.beginPath(); ctx.arc(x, y, R * 0.62, 0, 7); ctx.fill(); }
    else { const g = ctx.createRadialGradient(x, y, 0, x, y, R); g.addColorStop(0, s.c + "40"); g.addColorStop(1, s.c + "0a"); ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, R, 0, 7); ctx.fill(); ctx.strokeStyle = s.c + "40"; ctx.lineWidth = 1; ctx.stroke(); }
    // tasks orbiting
    const n = Math.min(s.n, 70); const rr = R + 6 * Math.min(cam.s, 1.5); const prof = ["#c4b5fd", "#67e8f9", "#67e8f9", "#fde047"];
    for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2 + t / (30000 + s.r * 300); ctx.fillStyle = prof[(i * 7 + id.length) % 4]; ctx.globalAlpha = 0.85; ctx.beginPath(); ctx.arc(x + Math.cos(a) * rr, y + Math.sin(a) * rr, Math.max(0.9, 1.3 * Math.min(cam.s, 1.4)), 0, 7); ctx.fill(); }
    ctx.globalAlpha = 1;
    const up = s.lab === "up"; const ly = up ? y - R - 22 * opt.fs : y + R + 20 * opt.fs;
    labels.push([1, x, ly, s.name, "#c3cde0", "center", font(13), 1]); labels.push([1, x, ly + 14 * opt.fs, s.sub || String(s.n), "#55627a", "center", font(10.5), 1]);
  }
  // In Progress moons
  const ip = STATES.in_progress; MOONS.forEach(([name, side, dy]) => { const [x, y] = toScreen(ip.x + side * 43, ip.y + dy); ctx.fillStyle = "rgba(167,139,250,.35)"; ctx.strokeStyle = "rgba(167,139,250,.6)"; ctx.beginPath(); ctx.arc(x, y, 4 * Math.min(cam.s, 1.5), 0, 7); ctx.fill(); ctx.stroke();
    labels.push([1, x + side * 10 * Math.min(cam.s, 1.5), y + 4 * opt.fs, name, "#94a3b8", side < 0 ? "right" : "left", font(10.5), 1]); });
}

// ---------- hit testing ----------
function hit(sx, sy) {
  const [wx, wy] = toWorld(sx, sy); let best = null, bd = Infinity; hoverStep = null;
  for (const it of items) {
    if (it.kind === "text") continue;
    const d = Math.hypot(it.x - wx, it.y - wy); const reach = Math.max(it.r + 4, 10 / cam.s);
    if (d < reach && d / reach < bd) { bd = d / reach; best = it; }
  }
  if (best && best.kind === "dag" && best.dag.steps.length > 1 && cam.s * 15 > 22) {
    const g = best.g || glyph(best.dag); let bi = -1, bdd = 9 / cam.s; g.pts.forEach((p, i) => { const d = Math.hypot(best.x + p.x - wx, best.y + p.y - wy); if (d < bdd) { bdd = d; bi = i; } }); if (bi >= 0) hoverStep = { dag: best.dag, i: bi };
  }
  if (best && best.kind === "cluster") { let bm = null, bdm = Infinity; best.members.forEach((m) => { const d = Math.hypot(best.x + m.dx - wx, best.y + m.dy - wy); if (d < bdm) { bdm = d; bm = m; } }); if (bm && bdm * cam.s < 9) hoverStep = { dag: bm.dag, member: true }; }
  if (best) return best;
  if (levelStack.length === 1 && !opt.sheet) for (const [id, s] of Object.entries(STATES)) if (Math.hypot(s.x - wx, s.y - wy) < s.r + 8) return { kind: "state", id, s };
  return null;
}
const tip = document.getElementById("tip");
function tieText(d) { return (TIES[d.name] || []).map((x) => x.kind === "cue" ? `runs on ${x.on}, beside ${x.event} (${STATES[x.source].name} → ${STATES[x.target].name})` : x.kind === "launches" ? `launches ${x.machine}` : x.source === x.target ? `writes ${x.event} (${STATES[x.source].name})` : `writes ${x.event} (${STATES[x.source].name} → ${STATES[x.target].name})`); }
function showTip(it, sx, sy) {
  if (!it) { tip.style.display = "none"; return; }
  let html = "";
  if (hoverStep && hoverStep.member) { const d = hoverStep.dag; html = `<b>${d.name}</b><small>one step · ${d.domain} · last run ${d.status}</small>`; }
  else if (it.kind === "dag") { const d = it.dag;
    if (hoverStep) { const s = d.steps[hoverStep.i]; html = `<code>${s.name}</code><small>${d.name} · step ${hoverStep.i + 1} of ${d.steps.length}${s.kind ? ` · ${s.kind}` : ""}${s.depends.length ? ` · after ${s.depends.join(", ")}` : " · first"} · ${stepStatus(d, s)}</small>`; }
    else { const ties = tieText(d); html = `<b>${d.name}</b><small>${d.steps.length} step${d.steps.length === 1 ? "" : "s"} · ${d.domain} · last run ${runs.has(d.name) ? "running" : d.status}${d.synthetic ? " · synthetic" : ""}</small>${ties.map((x) => `<small>${x}</small>`).join("")}`; } }
  else if (it.kind === "cluster") html = `<b>${it.members.length} one-step DAGs</b><small>${it.domain}: ${it.members.slice(0, 8).map((m) => m.dag.name).join(", ")}${it.members.length > 8 ? ", …" : ""}</small>`;
  else if (it.kind === "system") html = `<b>${it.domain}</b><small>${it.list.length} DAGs · ${it.list.filter((d) => d.steps.length > 1).length} multi-step · click to open</small>`;
  else if (it.kind === "state") html = `<b>${it.s.name}</b><small>${it.s.n} tasks</small>`;
  tip.innerHTML = html; tip.style.display = "block"; const w = tip.offsetWidth; tip.style.left = Math.min(sx + 14, W - RAIL - w - 8) + "px"; tip.style.top = sy + 16 + "px";
}

// ---------- the DAG panel ----------
const panel = document.getElementById("panel");
function openPanel(d) { panelDag = d; renderPanel(); }
function closePanel() { panelDag = null; panel.classList.remove("on"); }
function renderPanel() {
  const d = panelDag; if (!d) return; const run = runs.get(d.name); const pool = LIVE.pools.find((p) => p.name === d.pool);
  const st = run ? "running" : d.status; const col = COL[st === "succeeded" ? "ok" : st] || "#8b97ad";
  const when = d.finishedAt ? new Date(d.finishedAt).toLocaleTimeString("en-US", { timeZone: "America/Phoenix", hour: "2-digit", minute: "2-digit", hour12: false }) + " MST" : "never";
  panel.innerHTML = `<button class="x" aria-label="Close">×</button><h2>${d.name}</h2>
    <div class="meta">${d.domain} · <span class="chip" style="color:${col}">${run ? "running" : d.status}</span> · last run ${when}</div>
    ${tieText(d).length ? `<h4>Board</h4>${tieText(d).map((x) => `<div>${x}</div>`).join("")}` : ""}
    ${pool ? `<h4>Queue</h4><div>${pool.name} · ${(pool.running || 0) + (run ? 1 : 0)}/${pool.cap}</div>` : ""}
    <h4>Steps · ${d.steps.length}</h4>${d.steps.map((s) => { const v = stepStatus(d, s); return `<div class="step"><i style="${v === "not_started" || v === "pending" || v === "aborted" ? "border:1px solid #8b97ad" : `background:${COL[v === "succeeded" ? "ok" : v]}`}"></i><code>${s.name}</code><small title="${s.depends.join(", ")}">${s.depends.length > 2 ? `after ${s.depends.length} steps` : s.depends.length ? "after " + s.depends.join(", ") : "first"}</small></div>`; }).join("")}
    <button class="run" ${d.runSafe && !run ? "" : "disabled"} title="${d.runSafe ? "" : "not run-safe: it writes live state"}">${run ? "Running…" : "Run now"}</button>
    <div class="refusal"></div>`;
  panel.classList.add("on");
  panel.querySelector(".x").onclick = closePanel;
  panel.querySelector(".run").onclick = () => {
    const btn = panel.querySelector(".run"); btn.disabled = true; btn.textContent = "Starting…";
    setTimeout(() => { // simulated POST /api/run: a pool at its cap refuses
      if (pool && (pool.running || 0) >= pool.cap) { const r = panel.querySelector(".refusal"); r.textContent = `Refused: pool ${pool.name} is full (${pool.running}/${pool.cap}).`; r.classList.add("on"); btn.disabled = false; btn.textContent = "Run now"; return; }
      startRun(d, "manual"); renderPanel(); }, 500);
  };
}

// ---------- navigator, rail, mock chrome ----------
function clockText() { return new Date().toLocaleTimeString("en-US", { timeZone: "America/Phoenix", hour12: false }) + " MST"; }
function renderNav() {
  document.getElementById("navclock").textContent = new Date().toLocaleDateString("en-US", { timeZone: "America/Phoenix", month: "short", day: "numeric", year: "numeric" }) + ", " + clockText().slice(0, 5) + " MST";
  const L = document.getElementById("layers"); const top = levelStack[levelStack.length - 1];
  L.innerHTML = `<div class="lrow ${top.kind === "board" ? "on" : ""}" data-l="board"><span class="ring"></span><span>Board</span><span class="n">235</span></div>` +
    Object.entries(STATES).map(([id, s]) => `<div class="lrow sub" data-s="${id}"><span class="ring" style="width:7px;height:7px"></span><span>${s.name}</span><span class="n">${s.n}</span></div>`).join("") +
    (opt.place === "systems" && top.kind === "domain" ? `<div class="lrow sub on"><span class="ring" style="border-color:${DOMAIN_COLOR[top.domain]}"></span><span>${top.domain}</span><span class="n">${dags.filter((d) => d.domain === top.domain && !isTied(d)).length}</span></div>` : "");
  L.querySelectorAll("[data-l]").forEach((e) => (e.onclick = () => { levelStack = [{ kind: "board" }]; relayout(); }));
  L.querySelectorAll("[data-s]").forEach((e) => (e.onclick = () => { if (levelStack.length > 1) { levelStack = [{ kind: "board" }]; relayout(); } const s = STATES[e.dataset.s]; zoomOn(s.x, s.y, s.r * 2.2); }));
  renderPools();
  const crumb = document.getElementById("crumb");
  if (top.kind === "domain") { crumb.style.display = "block"; crumb.innerHTML = `<button id="cb">Board</button> › <b>${top.domain}</b> · ${dags.filter((d) => d.domain === top.domain && !isTied(d)).length} DAGs`; document.getElementById("cb").onclick = stepOut; }
  else crumb.style.display = "none";
}
function pushRecent(id, ev, cls, extra) { recent.unshift({ t: clockText().slice(0, 5), id, ev, cls, fresh: true }); renderRecent(); }
function renderRecent() {
  document.getElementById("recent").innerHTML = recent.slice(0, 60).map((r) => `<div class="${r.fresh ? "new" : ""}"><span class="t">${r.t}</span> <span class="id">${r.id}</span> <span class="${r.cls}">${r.ev}</span></div>`).join("");
  recent.forEach((r) => (r.fresh = false));
}
(function seedRecent() {
  const r = rng(11); const evs = ["worktree_ready in-progress", "lint_green in-progress", "ci_green in-progress", "ac_checkpointed in-progress", "committed in-progress", "pr_opened in-progress"];
  const runsSeed = ["rag-metrics", "cr-sweep", "graph-refresh", "main-follow", "apply-on-merge", "healthcheck", "grafana-rule-health", "session-transcript-stats"];
  for (let i = 0; i < 40; i++) { const m = 59 - Math.floor(i / 3); if (r() < 0.3) { const n = runsSeed[(r() * runsSeed.length) | 0]; const d = byName.get(n); recent.push({ t: `19:${String(m).padStart(2, "0")}`, id: `dagu/${n}`, ev: d.status, cls: d.status === "failed" ? "bad" : "ok" }); }
    else recent.push({ t: `19:${String(m).padStart(2, "0")}`, id: `DEMO-${3000 + ((r() * 40) | 0)}`, ev: evs[(r() * evs.length) | 0], cls: "ev" }); }
})();
const MOCK = [["glyph", "Glyph", [["classic", "Classic"], ["radiant", "Radiant"]]], ["one", "One-step", [["glint", "Glint"], ["dim", "Dim"], ["asterism", "Asterism"], ["cluster", "Cluster"]]],
  ["place", "Free DAGs", [["regions", "Regions"], ["systems", "Systems"], ["zodiac", "Zodiac"]]], ["tied", "Tied DAGs", [["path", "Beside path"], ["satellite", "Satellites"]]],
  ["n", "DAGs", [["51", "51 live"], ["150", "150"], ["400", "400"]]], ["fs", "Text", [["1", "100%"], ["1.25", "125%"], ["1.5", "150%"]]]];
function renderMock() {
  const m = document.getElementById("mock");
  m.innerHTML = `<span class="tag">Mockup</span>` + MOCK.map(([k, label, vals]) => `<span class="g"><span>${label}</span>${vals.map(([v, t]) => `<button data-k="${k}" data-v="${v}" class="${String(opt[k]) === v ? "on" : ""}">${t}</button>`).join("")}</span>`).join("") +
    `<span class="g"><button data-sheet class="${opt.sheet ? "on" : ""}">Glyph sheet</button><button data-run>Run apply-on-merge</button></span>`;
  m.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => { P.set(b.dataset.k, b.dataset.v); P.delete("s"); go(); }));
  m.querySelector("[data-sheet]").onclick = () => { P.set("sheet", opt.sheet ? "0" : "1"); P.delete("s"); go(); };
  m.querySelector("[data-run]").onclick = () => { const d = byName.get("apply-on-merge"); startRun(d, "merge"); const it = itemOf(d); if (it && !opt.sheet) { if (it.kind === "system") return; zoomOn(it.x, it.y, it.r); } openPanel(d); };
}
function go() { for (const [k] of MOCK) if (!P.has(k)) P.set(k, String(opt[k])); P.set("sheet", P.get("sheet") || (opt.sheet ? "1" : "0")); location.search = P.toString(); }

// ---------- levels ----------
function relayout(keepCam) { layoutLevel(); fitCam = computeFit(); if (!keepCam) flyTo(fitCam, 450); renderNav(); }
function drill(domain, from) {
  const z = { s: cam.s * 3, x: 0, y: 0 }; z.x = from[0] - (from[0] - cam.x) * 3; z.y = from[1] - (from[1] - cam.y) * 3; flyTo(z, 260);
  setTimeout(() => { levelStack.push({ kind: "domain", domain }); layoutLevel(); fitCam = computeFit(); cam = { s: fitCam.s * 0.4, x: fitCam.x + (W / 2) * 0.6 * 0.2, y: fitCam.y }; flyTo(fitCam, 420); renderNav(); }, 270);
}
function stepOut() {
  if (panelDag) return closePanel();
  if (Math.abs(cam.s - fitCam.s) > 1e-3 * fitCam.s || Math.abs(cam.x - fitCam.x) > 1) return flyTo(fitCam, 450);
  if (levelStack.length > 1) { levelStack.pop(); relayout(); }
}
function findAndOpen(d) {
  if (opt.place === "systems" && !isTied(d)) {
    const top = levelStack[levelStack.length - 1];
    if (top.kind !== "domain" || top.domain !== d.domain) { levelStack = [{ kind: "board" }, { kind: "domain", domain: d.domain }]; layoutLevel(); fitCam = computeFit(); cam = { ...fitCam }; renderNav(); }
  } else if (levelStack.length > 1) { levelStack = [{ kind: "board" }]; layoutLevel(); fitCam = computeFit(); cam = { ...fitCam }; renderNav(); }
  const it = itemOf(d); openPanel(d); if (it) { const m = it.kind === "cluster" ? it.members.find((q) => q.dag === d) : null; zoomOn(it.x + (m ? m.dx : 0), it.y + (m ? m.dy : 0), m ? 20 : it.r); }
}

// ---------- input ----------
let drag = null, downAt = null;
cv.addEventListener("mousemove", (e) => {
  if (drag) { cam = { ...cam, x: drag.cx + e.clientX - drag.x, y: drag.cy + e.clientY - drag.y }; drag.moved = drag.moved || Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 4; return; }
  hover = hit(e.clientX, e.clientY); cv.style.cursor = hover && hover.kind !== "state" ? "pointer" : hover ? "pointer" : "default"; showTip(hover, e.clientX, e.clientY);
});
cv.addEventListener("mouseleave", () => { hover = null; showTip(null); });
cv.addEventListener("mousedown", (e) => { if (e.button !== 0) return; downAt = [e.clientX, e.clientY]; if (cam.s > fitCam.s * 1.02) drag = { x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y, moved: false }; });
window.addEventListener("mouseup", (e) => {
  const moved = drag && drag.moved; drag = null; if (e.button !== 0 || !downAt || e.target !== cv) { downAt = null; return; } downAt = null; if (moved) return;
  const it = hit(e.clientX, e.clientY); if (!it) return;
  if (it.kind === "system") return drill(it.domain, [e.clientX, e.clientY]);
  if (it.kind === "dag") return openPanel(it.dag);
  if (it.kind === "cluster") { if (hoverStep && hoverStep.member) return openPanel(hoverStep.dag); return zoomOn(it.x, it.y, it.r); }
});
cv.addEventListener("contextmenu", (e) => { e.preventDefault(); stepOut(); });
cv.addEventListener("wheel", (e) => {
  e.preventDefault(); anim = null; const f = Math.exp(-e.deltaY * 0.0015); const s = Math.min(fitCam.s * 8, Math.max(fitCam.s, cam.s * f));
  if (s === fitCam.s && f < 1) { flyTo(fitCam, 200); return; }
  const k = s / cam.s; cam = { s, x: e.clientX - (e.clientX - cam.x) * k, y: e.clientY - (e.clientY - cam.y) * k };
}, { passive: false });
window.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "Escape") closePanel(); else if (e.key === "Backspace") { e.preventDefault(); stepOut(); } else if (e.key === "0") flyTo(fitCam, 450);
});
// search: states, DAGs and (systems) domains
const q = document.getElementById("q"), hits = document.getElementById("hits"); let hitList = [], sel = 0;
function renderHits() {
  const v = q.value.trim().toLowerCase(); if (!v) { hits.classList.remove("on"); hiTarget = null; return; }
  hitList = [...Object.entries(STATES).filter(([, s]) => s.name.toLowerCase().includes(v)).map(([id, s]) => ({ kind: "state", id, label: s.name, sub: "Board state" })),
    ...domains.filter((d) => d.toLowerCase().includes(v)).map((d) => ({ kind: "domain", domain: d, label: d, sub: "DAG domain" })),
    ...dags.filter((d) => d.name.includes(v)).map((d) => ({ kind: "dag", dag: d, label: d.name, sub: `DAG · ${d.domain}${isTied(d) ? " · on the Board" : ""}` }))].slice(0, 30);
  hits.innerHTML = hitList.length ? hitList.map((h, i) => `<button data-i="${i}" class="${i === sel ? "sel" : ""}">${h.label}<small>${h.sub}</small></button>`).join("") : `<button disabled>No match<small>&nbsp;</small></button>`;
  hits.classList.add("on");
  hits.querySelectorAll("[data-i]").forEach((b) => { b.onmouseenter = () => { const h = hitList[+b.dataset.i]; hiTarget = h.kind === "dag" ? itemOf(h.dag) : h.kind === "domain" ? items.find((i) => i.kind === "system" && i.domain === h.domain) : null; }; b.onmouseleave = () => (hiTarget = null); b.onclick = () => takeHit(hitList[+b.dataset.i]); });
}
function takeHit(h) {
  hits.classList.remove("on"); hiTarget = null; q.blur();
  if (h.kind === "dag") return findAndOpen(h.dag);
  if (h.kind === "state") { if (levelStack.length > 1) { levelStack = [{ kind: "board" }]; relayout(true); } const s = STATES[h.id]; return zoomOn(s.x, s.y, s.r * 2.2); }
  if (h.kind === "domain") { if (opt.place === "systems") { levelStack = [{ kind: "board" }, { kind: "domain", domain: h.domain }]; return relayout(); } const dc = deco.find((x) => x.domain === h.domain && x.members); if (dc && dc.members.length) { let cx = 0, cy = 0; dc.members.forEach((m) => { cx += m.x; cy += m.y; }); zoomOn(cx / dc.members.length, cy / dc.members.length, 140); } }
}
q.addEventListener("input", () => { sel = 0; renderHits(); });
q.addEventListener("keydown", (e) => { if (e.key === "Enter" && hitList[sel]) takeHit(hitList[sel]); else if (e.key === "Escape") { q.value = ""; renderHits(); q.blur(); } else if (e.key === "ArrowDown") { sel = Math.min(sel + 1, hitList.length - 1); renderHits(); e.preventDefault(); } else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); renderHits(); e.preventDefault(); } });

// ---------- start ----------
resize(); window.addEventListener("resize", () => { resize(); fitCam = computeFit(); cam = { ...fitCam }; });
const dm = P.get("domain") ?? SCENES[scene].domain; if (dm && opt.place === "systems") levelStack.push({ kind: "domain", domain: dm });
layoutLevel(); fitCam = computeFit(); cam = { ...fitCam }; renderNav(); renderRecent(); renderMock();
const startDag = P.get("dag") ?? SCENES[scene].dag;
if (startDag && byName.get(startDag)) { const d = byName.get(startDag); openPanel(d); const it = itemOf(d); if (it && (P.get("zoom") ?? SCENES[scene].zoom)) { const s = Math.min(fitCam.s * 8, Math.max(fitCam.s * 1.6, 130 / Math.max(it.r, 8))); cam = { s, x: NAV + (W - NAV - RAIL) / 2 - 160 - it.x * s, y: H / 2 - it.y * s }; } }
if (+(P.get("run") ?? SCENES[scene].run ?? 0)) startRun(byName.get(startDag || "apply-on-merge"), "merge");
// background runs: a DAG starts every few seconds, as the live sky does
setInterval(() => { const pool = dags.filter((d) => d.steps.length > 1 && !runs.has(d.name) && d.name !== "apply-on-merge"); if (pool.length && runs.size < 3 && Math.random() < 0.6) startRun(pool[(Math.random() * pool.length) | 0], "schedule"); }, 4000);
let lastClock = 0;
function frame(t) {
  if (anim) { const p = Math.min(1, (t - anim.t0) / anim.dur); const e = p < 0.5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2; cam = { s: anim.from.s + (anim.to.s - anim.from.s) * e, x: anim.from.x + (anim.to.x - anim.from.x) * e, y: anim.from.y + (anim.to.y - anim.from.y) * e }; if (p >= 1) anim = null; }
  tickRuns(t); draw(t);
  if (t - lastClock > 1000) { lastClock = t; document.getElementById("clock").textContent = "● live · " + clockText(); }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
