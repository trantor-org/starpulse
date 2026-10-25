// The Star Map's phase machines (Round 22, concept H): a machine is drawn only while a task uses it, as a branch that grows out of its sun's hub ring,
// takes the first free arc and retracts once no task needs it. A task rides the lines: hub, branch, station, and the Board's curves between suns.
import { bez, textW, type BEdge, type Galaxy, type Pt, type Scene } from "./scene";
import { PHASE, SUBM, rgba, tierColor, type DrawCtx, type Drawing } from "./draw";
import { glideTime } from "./sky";

/** Where a task sits on its sun's phase branches: a step of a machine, on the first ring (a phase) or the second (a machine one of those opened). */
export interface HPlace {
  machine: string;
  steps: string[];
  j: number;
  ring1: boolean;
  side?: { machine: string; steps: string[]; j: number };
}
type Node = Pt & { k: string };
interface Branch {
  key: string;
  sun: string;
  ring: 1 | 2;
  machine: string;
  steps: string[];
  parent?: string;
  pj: number;
  th: number;
  /** Which hub lane its stations ride (0 next to the hub, each further one LANE out) and which way round they run from `th`. */
  lane: number;
  dir: 1 | -1;
  ext: number;
  alive: boolean;
  seen: number;
  route: Node[];
  /** Index in `route` where this branch's own line starts; before it is its parent's. */
  own: number;
  st: number[];
  /** Each station's angle: a step apart, or further where the next spot would sit on a Board curve. */
  at: number[];
  /** Placed where no lane in reach was clear of the Board's curves, so its stations may sit on one. */
  loose?: 0 | 1 | 2;
  /** The sub-machines it was placed afresh for, once each, so their spokes clear a name. */
  bumped?: string[];
  /** The placed branches and curves a failed `allocate` was tried against. */
  tried?: string;
  /** The sun's geometry and placed neighbours the branch's place was last checked against. */
  ok?: string;
}
interface Mem {
  node: string;
  route: Node[];
  bks: string[];
  path: Node[];
  cum: number[];
  t0: number;
  dur: number;
  fade: { x: number; y: number } | null;
  last?: { sun: string; machine: string; steps: string[]; j: number };
  x: number;
  y: number;
  hold: string[];
}

const STEP1 = 0.236, D1 = 20, LANE = 28, PAD = 0.06, TAIL = 0.25, GAP = 0.12, CLEAR = 12, OFF = 5, FADE = 0.35, RING = 0.6, BOX = 16, NUDGE = 0.02;
const TAU = Math.PI * 2;
/** A ring-1 branch is a phase machine, drawn blue; a ring-2 branch is a sub-machine, drawn teal. */
const kind = (b: Branch) => (b.ring === 1 ? PHASE : SUBM);
const branches = new Map<string, Branch>(), mems = new Map<string, Mem>();
let lastNow = 0;

const at = (g: Pt, r: number, a: number, k: string): Node => ({ k, x: g.x + Math.cos(a) * r, y: g.y + Math.sin(a) * r });
const angle = (g: Pt, p: Pt) => Math.atan2(p.y - g.y, p.x - g.x);
const clash = (a0: number, a1: number, b0: number, b1: number, gap: number) => [-TAU, 0, TAU].some((s) => a0 < b1 + s + gap && b0 + s < a1 + gap);

const rad = (g: Galaxy, lane: number) => g.edge + D1 + lane * LANE;
/** A lane's angle per step: every lane spaces its stations the same distance apart, so an outer lane fits more of them. */
const stepAt = (g: Galaxy, lane: number) => (STEP1 * rad(g, 0)) / rad(g, lane);
/** The angle of the parent's station a ring-2 branch opened from. */
function phiOf(b: Branch) {
  return branches.get(b.parent!)!.at[b.pj];
}
type Claim = { lane: number; a0: number; a1: number };
/** The arcs a branch at `th` on `lane` holds: its own run (landing, stations, name) and the lanes its spoke or landing crosses on the way out;
 *  `room` adds the lane outside its run, where the names of the steps it holds reach. */
function claims(b: Branch, th: number, lane: number, dir: 1 | -1, room: boolean, angs: number[]): Claim[] {
  const far = angs[angs.length - 1], out: Claim[] = [];
  let from = th - dir * PAD, cross: [number, number] = [th, th], lo = 0;
  if (b.ring === 2) {
    const phi = phiOf(b);
    [from, cross, lo] = [phi - dir * PAD, [phi, phi], branches.get(b.parent!)!.lane + 1];
  }
  const [a0, a1] = [Math.min(from, far + dir * TAIL), Math.max(from, far + dir * TAIL)];
  out.push({ lane, a0, a1 });
  if (room) out.push({ lane: lane + 1, a0, a1 });
  for (let l = lo; l < lane; l++) out.push({ lane: l, a0: Math.min(...cross) - PAD, a1: Math.max(...cross) + PAD });
  return out;
}
const hit = (A: Claim[], B: Claim[]) => A.some((p) => B.some((q) => p.lane === q.lane && clash(p.a0, p.a1, q.a0, q.a1, GAP)));
type Box = { x0: number; y0: number; x1: number; y1: number };
/** The box a branch's machine name takes, drawn past its last station as `drawBranches` draws it, at `px` sky units to the screen pixel. */
function nameBox(b: Branch, g: Galaxy, lane: number, dir: 1 | -1, angs: number[], px: number): Box {
  const size = 9.5 * px, a = angs[angs.length - 1] + dir * 0.12, c = Math.cos(a), R = rad(g, lane) + (Math.abs(c) <= 0.2 ? size : 0);
  const x = g.x + Math.cos(a) * R, y = g.y + Math.sin(a) * R, w = textW(b.machine, size), x0 = c > 0.2 ? x : c < -0.2 ? x - w : x - w / 2;
  return { x0, y0: y - 0.6 * size, x1: x0 + w, y1: y + 0.6 * size };
}
type Spot = { x: number; y: number; align: CanvasTextAlign; box: Box };
/** Where each held step's name prints, at `px` sky units to the screen pixel: out past its station, a line further out, inside it
 *  towards the sun, (above or below the sun) beside it, or up to four lines further out, whichever first clears every printed name, every other station, every branch's line and the step names placed before it; else the one that meets fewest. */
function stepSpots(sc: Scene, px: number, held: (node: string) => number): Map<string, Spot> {
  const size = 9 * px, out = new Map<string, Spot>(), bs = [...branches.values()].filter((b) => sc.galaxies[b.sun]);
  const fixed = [...sc.names, ...(sc.hangars ?? []), ...bs.filter((b) => !Number.isNaN(b.th)).map((b) => nameBox(b, sc.galaxies[b.sun], b.lane, b.dir, b.at, px))];
  const stations = bs.flatMap((b) => b.st.flatMap((i) => (b.route[i] ? [b.route[i]] : [])));
  const lines = bs.flatMap((b) => b.route.slice(b.own + (b.parent ? 1 : 0)));
  for (const b of bs) {
    const g = sc.galaxies[b.sun];
    b.steps.forEach((name, s) => {
      const n = held(`${b.key}#${s}`), self = b.route[b.st[s]];
      if (!n || !self) return;
      const a = angle(g, self), r = Math.hypot(self.x - g.x, self.y - g.y);
      const c = Math.cos(a), mid = Math.abs(c) <= 0.2, w = textW(name.replace(/_/g, " "), size);
      const spot = (R: number, side: number): Spot => {
        const x = g.x + c * R, y = g.y + Math.sin(a) * R, align = side > 0.2 ? "left" : side < -0.2 ? "right" : "center";
        const x0 = align === "left" ? x : align === "right" ? x - w : x - w / 2;
        return { x, y, align, box: { x0, y0: y - 0.6 * size, x1: x0 + w, y1: y + 0.6 * size } };
      };
      const R = r + 8 + OFF * (Math.min(n, 3) - 1) + (mid ? size : 0), taken = [...fixed, ...[...out.values()].map((o) => o.box)];
      const hits = (t: Spot) => taken.filter((o) => meet(t.box, o, 0)).length + stations.filter((p) => Math.hypot(p.x - self.x, p.y - self.y) > 0.5 && inBox(p, t.box, 0)).length + lines.filter((p) => inBox(p, t.box, 0)).length;
      const tries = [spot(R, c), spot(R + 1.4 * size, c), spot(r - 8 - (mid ? size : 0), -c), ...(mid ? [spot(R - size, 1), spot(R - size, -1)] : []), ...[2, 3, 4].map((k) => spot(R + 1.4 * k * size, c))];
      out.set(`${b.key}#${s}`, tries.reduce((x, y) => (hits(y) < hits(x) ? y : x)));
    });
  }
  return out;
}
const inBox = (p: Pt, n: Box, m: number) => p.x > n.x0 - m && p.x < n.x1 + m && p.y > n.y0 - m && p.y < n.y1 + m;
const meet = (a: Box, n: Box, m: number) => a.x0 < n.x1 + m && n.x0 < a.x1 + m && a.y0 < n.y1 + m && n.y0 < a.y1 + m;
/** Where a branch at `th` on `lane` sits on the sky: its stations, then its spoke out from the hub (a ring-2 branch's, from its parent's
 *  station). A station may not sit on a Board curve, nor a spoke leave the hub on or run along one leaving this sun; arcs and spokes may cross them. */
function spots(b: Branch, g: Galaxy, th: number, lane: number, angs: number[]): { st: Pt[]; spoke: Pt[] } {
  const r = rad(g, lane), st = angs.map((a) => at(g, r, a, "")), spoke: Pt[] = [];
  const [p, q] = b.ring === 1 ? [at(g, g.edge, th, ""), st[0]] : [at(g, rad(g, branches.get(b.parent!)!.lane), phiOf(b), ""), at(g, r, phiOf(b), "")];
  const m = Math.ceil(Math.hypot(q.x - p.x, q.y - p.y) / 4);
  for (let i = 0; i <= m; i++) spoke.push({ x: p.x + ((q.x - p.x) * i) / m, y: p.y + ((q.y - p.y) * i) / m });
  return { st, spoke };
}
/** The nearest free place for a new branch: the lowest lane whose stations stay CLEAR of the Board's curves, whose spoke runs along none
 *  leaving this sun, and whose arc is clear of the sun's other branches, the names of their held steps included where there is room. A ring-1 branch stays as near its preferred angle as it can; a
 *  ring-2 branch runs straight out from its parent's station and turns square onto its lane, either way round, its first station on the turn where it fits. */
function fitter(b: Branch, sc: Scene) {
  const g = sc.galaxies[b.sun];
  const base = b.ring === 1 ? 0 : branches.get(b.parent!)!.lane + 1, reach = rad(g, base + LANES + 1) + CLEAR;
  const sample = (e: BEdge) => Array.from({ length: 65 }, (_, i) => bez(e.p0!, e.c!, e.p1!, i / 64)).filter((q) => Math.hypot(q.x - g.x, q.y - g.y) < reach);
  const drawn = sc.bEdges.filter((e) => e.p0 && e.c && e.p1), all = drawn.flatMap(sample);
  const docked = drawn.filter((e) => e.source === b.sun || e.target === b.sun).flatMap(sample);
  const close = (p: Pt, qs: Pt[]) => qs.some((q) => Math.hypot(p.x - q.x, p.y - q.y) < CLEAR);
  // a spoke crossing a curve is near it for a few samples; one running along it, or leaving the hub on top of it, is near for most
  // the fitted view frames the suns, so a station outside their box would open off screen
  const gs = Object.values(sc.galaxies), x0 = Math.min(...gs.map((o) => o.x - o.R)) - BOX, x1 = Math.max(...gs.map((o) => o.x + o.R)) + BOX;
  const y0 = Math.min(...gs.map((o) => o.y - o.R)) - BOX, y1 = Math.max(...gs.map((o) => o.y + o.R)) + BOX;
  const off = (st: Pt[]) => st.some((p) => p.x < x0 || p.x > x1 || p.y < y0 || p.y > y1);
  const onCurve = ({ st, spoke }: { st: Pt[]; spoke: Pt[] }) => st.some((p) => close(p, all)) || (b.ring === 1 && close(spoke[0], docked)) || spoke.filter((p) => close(p, docked)).length * 4 > 3 * CLEAR;
  // a station may not sit on a printed name: a state's label, another level's or another branch's machine name; nor may this branch's
  // machine name print over a station or a name. Step names find their own clear side as they print (stepSpots)
  const px = sc.px ?? 1, placed = [...branches.values()].filter((o) => o !== b && !Number.isNaN(o.th) && sc.galaxies[o.sun]);
  const labels = placed.map((o) => nameBox(o, sc.galaxies[o.sun], o.lane, o.dir, o.at, px));
  // nor over the name of a step another branch holds a dot on, where that name prints now
  const held = (node: string) => [...mems.values()].filter((m) => m.node === node).length;
  const steps = [...stepSpots(sc, px, held)].filter(([node]) => !node.startsWith(`${b.key}#`)).map(([, s]) => s.box);
  const texts = [...sc.names, ...(sc.hangars ?? []), ...labels, ...steps];
  const stations = placed.flatMap((o) => o.at.map((a) => at(sc.galaxies[o.sun], rad(sc.galaxies[o.sun], o.lane), a, "")));
  const named = (p: Pt) => texts.some((n) => inBox(p, n, OFF));
  // the arc between its stations and the spoke out to them stay off every printed name too
  const lined = ({ st, spoke }: { st: Pt[]; spoke: Pt[] }, lane: number) => {
    const r = rad(g, lane), a0 = b.ring === 1 ? angle(g, st[0]) : angle(g, spoke[spoke.length - 1]), a1 = angle(g, st[st.length - 1]), d = Math.atan2(Math.sin(a1 - a0), Math.cos(a1 - a0));
    const m = Math.max(Math.ceil((Math.abs(d) * r) / 4), 1), arc = Array.from({ length: m + 1 }, (_, i) => at(g, r, a0 + (d * i) / m, ""));
    return [...arc, ...spoke].some(named);
  };
  // a ring-1 place leaves the spoke each sub-machine runs straight out from its station clear of names too, out to the sub-machine's first
  // lane, or out to the furthest lane it may take once it was placed afresh for it
  const kids = [...branches.values()].filter((o) => o.parent === b.key);
  const ray = (c: Branch) => (b.bumped?.includes(c.key) ? LANES + 1 : 1) * LANE;
  const rayed = (lane: number, angs: number[]) => kids.some((c) => Array.from({ length: Math.ceil(ray(c) / 4) + 1 }, (_, i) => at(g, rad(g, lane) + i * 4, angs[c.pj], "")).some(named));
  const labelled = (n: Box, st: Pt[]) => texts.some((o) => meet(n, o, OFF)) || [...stations, ...st].some((p) => inBox(p, n, OFF));
  const live = placed.filter((o) => o.sun === b.sun && o.key !== b.parent && o.parent !== b.key);
  const others = [true, false].map((room) => live.flatMap((o) => claims(o, o.th, o.lane, o.dir, room, o.at)));
  // the next station steps on round its lane until it clears every curve, by at most another step: a curve may pass between two stations
  const walk = (th: number, lane: number, dir: 1 | -1) => {
    const r = rad(g, lane), step = stepAt(g, lane), angs = [th];
    for (let s = 1; s < b.steps.length; s++) {
      let a = angs[s - 1] + dir * step;
      for (let n = 0; n < step / NUDGE && close(at(g, r, a, ""), all); n++) a += dir * NUDGE;
      angs.push(a);
    }
    return angs;
  };
  /** The station angles a place at `th` gives, or null when it does not fit; a `loose` place may sit on a Board curve (1), and failing that run its line over a name (2), never a station on a name, nor its own name on a station. */
  const fits = (th: number, lane: number, dir: 1 | -1, room: boolean, loose: 0 | 1 | 2 = 0) => {
    const angs = walk(th, lane, dir), sp = spots(b, g, th, lane, angs);
    return !hit(claims(b, th, lane, dir, room, angs), others[room ? 0 : 1]) && !off(sp.st) && !(loose ? false : onCurve(sp)) && !sp.st.some(named) && !(loose > 1 ? false : lined(sp, lane) || rayed(lane, angs)) && !labelled(nameBox(b, g, lane, dir, angs, px), sp.st) ? angs : null;
  };
  return { g, base, fits };
}
/** A ring-2 branch looks no further round than this from its parent's station: past it the next lane out is nearer than the arc there. */
const NEAR = 0.6;
/** A branch grows at most this many lanes past its first: rather than go further out it crosses a Board curve, and only to clear a name does it take one lane more. */
const LANES = 3;
function allocate(b: Branch, sc: Scene, prefer: number) {
  const { base, fits } = fitter(b, sc), n = b.ring === 2 ? 2 * Math.round(NEAR / 0.05) + 1 : 2 * Math.ceil(Math.PI / 0.05);
  for (const loose of [0, 1, 2] as const)
  for (let lane = base; lane < base + LANES + (loose ? 1 : 0); lane++)
    for (const room of [true, false])
      for (let i = 0; i <= n; i++) {
        const dir: 1 | -1 = b.ring === 2 && i % 2 ? -1 : 1, k = b.ring === 2 ? Math.floor(i / 2) : Math.ceil(i / 2);
        const th = b.ring === 2 ? prefer + dir * k * 0.05 : prefer + (i % 2 ? 1 : -1) * k * 0.05;
        const angs = fits(th, lane, dir, room, loose);
        if (angs) return Object.assign(b, { th, lane, dir, at: angs, loose });
      }
}
function ensure(key: string, sun: string, ring: 1 | 2, machine: string, steps: string[], parent?: string, pj = 0): Branch {
  let b = branches.get(key);
  if (!b) branches.set(key, (b = { key, sun, ring, machine, steps, parent, pj, th: NaN, lane: 0, dir: 1, ext: 0, alive: false, seen: -1, route: [], own: 0, st: [], at: [] }));
  b.alive = true;
  return b;
}
function wake(key: string) {
  for (let b = branches.get(key); b; b = b.parent ? branches.get(b.parent) : undefined) b.alive = true;
}
/** The branch's nodes from the hub out: its parent's line to the station it opened from, then its own stations with samples between them. */
function shape(b: Branch, g: Galaxy) {
  const out: Node[] = [], st: number[] = [], r = rad(g, b.lane), A = b.at;
  if (b.ring === 1) out.push(at(g, g.edge, b.th, `${b.key}:h`));
  else {
    // square off the parent: straight out from its station to this lane, then round it to the first station, which sits on the turn when it can
    const p = branches.get(b.parent!)!, phi = phiOf(b), r0 = rad(g, p.lane), n = Math.ceil((r - r0) / 4);
    out.push(...p.route.slice(0, p.st[b.pj] + 1));
    b.own = out.length - 1;
    for (let i = 1; i < n; i++) out.push(at(g, r0 + ((r - r0) * i) / n, phi, `${b.key}:s${i}`));
    const m = Math.ceil(Math.abs(b.th - phi) / 0.08);
    if (m) out.push(at(g, r, phi, `${b.key}:r`));
    for (let i = 1; i < m; i++) out.push(at(g, r, phi + ((b.th - phi) * i) / m, `${b.key}:c${i}`));
  }
  b.steps.forEach((_, s) => {
    if (s) for (let i = 1; i < 5; i++) out.push(at(g, r, A[s - 1] + ((A[s] - A[s - 1]) * i) / 5, `${b.key}:${s}.${i}`));
    st.push(out.length);
    out.push(at(g, r, A[s], `${b.key}:${s}`));
  });
  b.route = out;
  b.st = st;
}
/** Points along the sun's hub ring from p to q, the short way round. */
function arc(g: Galaxy, p: Pt, q: Pt): Node[] {
  const a = angle(g, p), rp = Math.hypot(p.x - g.x, p.y - g.y), rq = Math.hypot(q.x - g.x, q.y - g.y);
  let d = angle(g, q) - a;
  d -= TAU * Math.round(d / TAU);
  const m = Math.ceil(Math.abs(d) / 0.1), out: Node[] = [];
  for (let i = 1; i < m; i++) out.push(at(g, rp + ((rq - rp) * i) / m, a + (d * i) / m, `arc${i}`));
  return out;
}
function common(a: Node[], b: Node[]) {
  let c = 0;
  while (c < a.length && c < b.length && a[c].k === b[c].k) c++;
  return c;
}
/** The way between two places, on lines only: back down the old branch, round the hub or across the Board's curve, up the new one. */
function travel(sc: Scene, sa: string, A: Node[], sb: string, B: Node[]): Node[] | null {
  const rev = [...A].reverse();
  if (sa === sb) {
    const c = common(A, B);
    return c ? [...A.slice(c).reverse(), A[c - 1], ...B.slice(c)] : [...rev, ...arc(sc.galaxies[sa], A[0], B[0]), ...B];
  }
  const fw = sc.bEdges.find((e) => e.source === sa && e.target === sb && e.p0), bw = fw ? null : sc.bEdges.find((e) => e.source === sb && e.target === sa && e.p0);
  const e = fw ?? bw;
  if (!e) return null;
  const pts = Array.from({ length: 25 }, (_, i) => ({ k: `e${i}`, ...bez(e.p0!, e.c!, e.p1!, fw ? i / 24 : 1 - i / 24) }));
  return [...rev, ...arc(sc.galaxies[sa], A[0], pts[0]), ...pts, ...arc(sc.galaxies[sb], pts[24], B[0]), ...B];
}
const lengths = (p: Pt[]) => p.reduce<number[]>((c, q, i) => (c.push(i ? c[i - 1] + Math.hypot(q.x - p[i - 1].x, q.y - p[i - 1].y) : 0), c), []);
function along(p: Pt[], cum: number[], d: number): Pt {
  let i = 1;
  while (i < p.length - 1 && cum[i] < d) i++;
  const s = cum[i] - cum[i - 1], u = s ? Math.min(1, Math.max(0, (d - cum[i - 1]) / s)) : 1;
  return { x: p[i - 1].x + (p[i].x - p[i - 1].x) * u, y: p[i - 1].y + (p[i].y - p[i - 1].y) * u };
}

/** Each fully drawn branch's own line, from its landing (or the hub) to its last station: what the overlap check measures. Siblings share the
 *  station they open from, so a ring-2 line starts past it. */
export const branchLines = () =>
  [...branches.values()].filter((b) => b.ext >= 1 && b.route.length).map((b) => ({ key: b.key, sun: b.sun, ring: b.ring, parent: b.parent, th: +b.th.toFixed(3), lane: b.lane, dir: b.dir, n: b.steps.length, pj: b.pj, loose: b.loose, pts: b.route.slice(b.own + (b.parent ? 1 : 0)) }));
/** Every printed name that meets another name or a station it does not label, on fully drawn branches: what the text check counts. */
export function textHits(sc: Scene): string[] {
  const px = sc.px ?? 1, bs = [...branches.values()].filter((b) => b.ext >= 1 && b.route.length && sc.galaxies[b.sun]), out: string[] = [];
  const spots = stepSpots(sc, px, (node) => [...mems.values()].filter((m) => m.node === node).length);
  const texts = [
    ...[...sc.names, ...(sc.hangars ?? [])].map((n) => ({ of: `name:${n.of}`, n, mine: [] as Pt[] })),
    ...bs.flatMap((b) => {
      const g = sc.galaxies[b.sun], st = b.at.map((a) => at(g, rad(g, b.lane), a, ""));
      return [{ of: `${b.key}:machine`, n: nameBox(b, g, b.lane, b.dir, b.at, px), mine: [] as Pt[] }, ...b.steps.flatMap((_, i) => { const t = spots.get(`${b.key}#${i}`); return t ? [{ of: `${b.key}:step${i}`, n: t.box, mine: st }] : []; })];
    }),
  ];
  const stations = bs.flatMap((b) => b.at.map((a) => ({ of: b.key, p: at(sc.galaxies[b.sun], rad(sc.galaxies[b.sun], b.lane), a, "") })));
  texts.forEach((t, i) => {
    texts.slice(i + 1).forEach((u) => meet(t.n, u.n, 0) && !(t.of.startsWith("name:") && u.of.startsWith("name:")) && out.push(`${t.of}~${u.of}`));
    stations.forEach((s) => !t.mine.includes(s.p) && !(t.of.startsWith(`${s.of}:step`)) && inBox(s.p, t.n, 0) && out.push(`${t.of}@${s.of}`));
    bs.forEach((b) => b.route.slice(b.own + (b.parent ? 1 : 0)).some((p) => inBox(p, t.n, 0)) && out.push(`${t.of}/${b.key}:line`));
  });
  return out;
}
/** Places every Board task with a phase place for this frame and grows or retracts the branches; true while anything still animates. */
export function placeBranches(sc: Scene, now: number): boolean {
  const dt = Math.min(0.1, Math.max(0, now - lastNow)), tasks = sc.tasks.filter((k) => !k.today && sc.galaxies[(k.host as Galaxy).id] === k.host);
  lastNow = now;
  let busy = false;
  for (const b of branches.values()) b.alive = false;
  const want = new Map<string, { b: Branch; j: number }>();
  for (const k of tasks) {
    const h = k.h, sun = (k.host as Galaxy).id, m = mems.get(k.id);
    if (!h) continue;
    const r1 = () => ensure(`${sun}|${h.machine}`, sun, 1, h.machine, h.steps);
    let b: Branch;
    const par = !h.ring1 && (m?.last?.sun === sun && m.last.machine !== h.machine ? m.last : h.side);
    if (h.ring1 || !par) b = r1();
    else {
      const p = ensure(`${sun}|${par.machine}`, sun, 1, par.machine, par.steps);
      p.seen = Math.max(p.seen, par.j);
      b = ensure(`${p.key}|${h.machine}`, sun, 2, h.machine, h.steps, p.key, par.j);
    }
    b.seen = Math.max(b.seen, h.j);
    want.set(k.id, { b, j: h.j });
  }
  for (const m of mems.values()) for (const key of m.hold) wake(key);
  for (const b of branches.values()) if (b.parent && b.alive) wake(b.parent);
  for (const ring of [1, 2]) {
    // a place is kept only while it still fits: once the sun moves or grows, a curve or name moves onto it, or a neighbour is placed, it is
    // checked again, and a branch that no longer fits is placed afresh (its dots glide to the new place)
    for (const b of branches.values()) {
      if (b.ring !== ring || Number.isNaN(b.th) || !sc.galaxies[b.sun] || (b.parent && !branches.has(b.parent))) continue;
      const g = sc.galaxies[b.sun], near = [...branches.values()].filter((o) => o !== b && o.sun === b.sun && !Number.isNaN(o.th));
      const ok = [sc.bEdges.length, sc.names.length, sc.hangars?.length ?? 0, Math.round(g.x), Math.round(g.y), Math.round(g.edge), ...near.map((o) => `${o.key}@${o.lane}@${o.th.toFixed(2)}`)].join();
      if (b.ok === ok) continue;
      b.ok = ok;
      const angs = b.parent && Number.isNaN(branches.get(b.parent)!.th) ? null : fitter(b, sc).fits(b.th, b.lane, b.dir, false, b.loose);
      if (angs) {
        b.at = angs;
        continue;
      }
      b.th = NaN;
      b.tried = b.ok = undefined;
      for (const m of mems.values()) if (m.node.startsWith(`${b.key}#`)) m.node = `${b.sun}|moved`;
    }
    for (const b of branches.values()) {
      if (b.ring !== ring || !Number.isNaN(b.th)) continue;
      if (b.parent && (!branches.has(b.parent) || Number.isNaN(branches.get(b.parent)!.th))) continue;
      const k = tasks.find((t) => want.get(t.id)?.b === b), m = k && mems.get(k.id), g = sc.galaxies[b.sun];
      // a branch with no free place waits for one; it is tried again only once its sun's placed branches or the Board's curves change
      const sig = [sc.bEdges.length, ...[...branches.values()].filter((o) => o.sun === b.sun && !Number.isNaN(o.th)).map((o) => `${o.key}@${o.lane}`)].join();
      if (b.tried === sig) continue;
      const at = ring === 2 ? phiOf(b) : m ? angle(g, m) : NaN;
      allocate(b, sc, Number.isFinite(at) ? at : -Math.PI / 2);
      b.tried = sig;
      // a sub-machine that fits only with its line over a name places its parent afresh, once for each such sub-machine, clear of their spokes
      const par = b.parent ? branches.get(b.parent)! : undefined;
      if (par && !par.bumped?.includes(b.key) && (Number.isNaN(b.th) || b.loose === 2)) {
        Object.assign(par, { th: NaN, tried: undefined, ok: undefined, bumped: [...(par.bumped ?? []), b.key] });
        // every sub-machine of it runs out from its stations, so each is placed afresh after it
        const fam = [par, ...[...branches.values()].filter((o) => o.parent === par.key)];
        for (const o of fam.slice(1)) Object.assign(o, { th: NaN, tried: undefined, ok: undefined });
        for (const m of mems.values()) if (fam.some((o) => m.node.startsWith(`${o.key}#`))) m.node = `${b.sun}|moved`;
      }
    }
  }
  const kids = new Set([...branches.values()].flatMap((b) => (b.parent ? [b.parent] : [])));
  for (const b of [...branches.values()]) {
    if (!sc.galaxies[b.sun] || (b.parent && !branches.has(b.parent))) {
      branches.delete(b.key);
      continue;
    }
    if (b.alive) b.ext = Math.min(1, b.ext + dt / 0.7);
    else if (!kids.has(b.key)) b.ext -= dt / 0.6;
    // a branch opened on a frame no time has passed since is still wanted, not retracted
    if (b.ext <= 0 && !b.alive) branches.delete(b.key);
    else if (b.ext < 1) busy = true;
  }
  for (const ring of [1, 2]) for (const b of branches.values()) if (b.ring === ring) shape(b, sc.galaxies[b.sun]);
  // a dot's stack index among those on its station, by id
  const stacks = new Map<string, string[]>();
  for (const [id, w] of want) stacks.set(`${w.b.key}#${w.j}`, [...(stacks.get(`${w.b.key}#${w.j}`) ?? []), id].sort());
  for (const k of tasks) {
    const sun = (k.host as Galaxy).id, g = sc.galaxies[sun];
    let w = want.get(k.id), route: Node[], node: string, bks: string[];
    // a dot whose place is being placed afresh holds where it is until the place has one
    if (w && !(Number.isFinite(w.b.th) && (!w.b.parent || Number.isFinite(branches.get(w.b.parent)?.th ?? NaN)))) {
      const held = mems.get(k.id);
      if (held) {
        [k.x, k.y, k.moving] = [held.x, held.y, false];
        continue;
      }
      w = undefined;
    }
    if (w) {
      const i = stacks.get(`${w.b.key}#${w.j}`)!.indexOf(k.id), s = w.b.route[w.b.st[w.j]];
      route = w.b.route.slice(0, w.b.st[w.j] + 1);
      // a later dot on the same station sits OFF further out from the sun per dot, where its label already steps out to
      const l = Math.hypot(s.x - g.x, s.y - g.y) || 1;
      if (i) route.push({ k: `${s.k}+${i}`, x: s.x + ((s.x - g.x) / l) * OFF * i, y: s.y + ((s.y - g.y) / l) * OFF * i });
      node = `${w.b.key}#${w.j}`;
      bks = w.b.parent ? [w.b.parent, w.b.key] : [w.b.key];
    } else {
      route = [at(g, g.edge, angle(g, k), `orbit:${sun}:h`), { k: `orbit:${sun}:${k.id}`, x: k.x, y: k.y }];
      node = `orbit:${sun}`;
      bks = [];
    }
    let m = mems.get(k.id);
    if (!m) mems.set(k.id, (m = { node, route, bks, path: [route.at(-1)!], cum: [0], t0: now - 9, dur: 0.8, fade: null, x: route.at(-1)!.x, y: route.at(-1)!.y, hold: [] }));
    else if (m.node !== node) {
      const oldSun = m.node.startsWith("orbit:") ? m.node.slice(6) : m.node.split("|")[0], p = travel(sc, oldSun, m.route, sun, route);
      // a dot still gliding keeps to the line: it finishes the rest of its way, dropping any stretch the new way would ride straight back
      const u = (now - m.t0) / m.dur, mid = p && !m.fade && u < 1 && m.path.length > 1, gone = u * m.cum.at(-1)!, next = m.cum.findIndex((c) => c > gone);
      const rest = mid ? m.path.slice(next < 1 ? m.path.length - 1 : next) : [], q = p ? [...p] : [];
      while (rest.length >= 2 && q.length >= 2 && rest.at(-2)!.k === q[1].k) {
        rest.pop();
        q.shift();
      }
      m.path = p ? [{ k: "cur", x: m.x, y: m.y }, ...rest.slice(0, -1), ...(rest.length ? q : q.slice(1))] : [route.at(-1)!];
      m.cum = lengths(m.path);
      m.dur = p ? glideTime(m.cum.at(-1)!) : 2 * FADE;
      m.fade = p ? null : { x: m.x, y: m.y };
      m.t0 = now;
      m.hold = [...new Set([...(mid ? m.hold : []), ...m.bks])];
      [m.node, m.bks] = [node, bks];
    }
    m.route = route;
    m.path[m.path.length - 1] = route.at(-1)!; // the end follows the place as its branch grows or its orbit turns
    if (m.path.length > 1) m.cum = lengths(m.path);
    const u = Math.min(1, (now - m.t0) / m.dur);
    let q: Pt = route.at(-1)!, alpha = 1;
    if (m.fade) {
      if (u < 0.5) [q, alpha] = [m.fade, 1 - u * 2];
      else alpha = u * 2 - 1;
    } else if (u < 1 && m.path.length > 1) q = along(m.path, m.cum, u * m.cum.at(-1)!);
    if (u >= 1) {
      m.hold = [];
      m.fade = null;
    } else busy = true;
    [m.x, m.y] = [q.x, q.y];
    if (w && !w.b.parent) m.last = { sun, machine: w.b.machine, steps: w.b.steps, j: w.j };
    const i = w ? stacks.get(`${w.b.key}#${w.j}`)!.indexOf(k.id) : 0, age = (now - m.t0 - m.dur) / RING;
    k.x = q.x;
    k.y = q.y;
    k.moving = u < 1 && !m.fade;
    k.alpha = i >= 3 && u >= 1 ? 0 : alpha;
    k.arrive = w && age >= 0 && age < 1 && now - m.t0 < 9 ? { x: q.x, y: q.y, r: 6, col: "#c084fc", age, grow: 18 } : null;
  }
  for (const id of [...mems.keys()]) if (!tasks.some((k) => k.id === id)) mems.delete(id);
  return busy;
}

/** The live branches, their stations and the names of the steps a dot sits on, then the movers' comet tails; drawTasks draws the heads. */
export function drawBranches(dc: DrawCtx, d: Drawing, sc: Scene) {
  const { cx } = dc, lw = 1.1 / Math.max(1, dc.ZS * 0.8), suns = new Map<string, number>();
  for (const b of branches.values()) suns.set(b.sun, Math.max(suns.get(b.sun) ?? 0, b.ext));
  for (const [sun, e] of suns) {
    const g = sc.galaxies[sun];
    if (g) d.circle(g.x, g.y, g.edge, rgba("#c4b5fd", 0.16 * e), lw);
  }
  const occ = new Map<string, number>();
  for (const m of mems.values()) if (m.node.includes("#")) occ.set(m.node, (occ.get(m.node) ?? 0) + 1);
  const spots = stepSpots(sc, d.labPx(1), (node) => occ.get(node) ?? 0);
  for (const b of branches.values()) {
    const g = sc.galaxies[b.sun], own = b.route.slice(b.own), cum = lengths(own), reach = b.ext * cum.at(-1)!;
    if (!g || own.length < 2) continue;
    cx.strokeStyle = rgba(kind(b), 0.45 * Math.min(1, b.ext * 2));
    cx.lineWidth = lw;
    cx.beginPath();
    cx.moveTo(own[0].x, own[0].y);
    for (let i = 1; i < own.length && cum[i - 1] < reach; i++) {
      const p = cum[i] <= reach ? own[i] : along(own, cum, reach);
      cx.lineTo(p.x, p.y);
    }
    cx.stroke();
    b.steps.forEach((name, s) => {
      const p = b.route[b.st[s]], n = occ.get(`${b.key}#${s}`) ?? 0;
      if (cum[b.st[s] - b.own] > reach + 0.01) return;
      if (s <= b.seen) d.dot(p.x, p.y, 2.2 / Math.max(1, dc.ZS * 0.5), rgba(kind(b), 0.85));
      else d.circle(p.x, p.y, 2.2 / Math.max(1, dc.ZS * 0.5), rgba(kind(b), 0.55), lw);
      if (!n) return;
      const t = spots.get(`${b.key}#${s}`), a = angle(g, p);
      if (!t) return;
      d.text(name.replace(/_/g, " "), t.x, t.y, d.labPx(9), rgba("#d8c8f5", 0.72 * b.ext), t.align, 300);
      if (n > 3) d.text(`+${n - 3}`, t.x + Math.cos(a) * d.labPx(9) * 4, t.y + Math.sin(a) * d.labPx(9) * 4, d.labPx(8), rgba("#d8c8f5", 0.6 * b.ext));
    });
    // a name centred above or below the sun would sit on its own arc, so it moves a line further out
    const end = b.route.at(-1)!, a = angle(g, end) + b.dir * 0.12, c = Math.cos(a), R = Math.hypot(end.x - g.x, end.y - g.y) + (Math.abs(c) <= 0.2 ? d.labPx(9.5) : 0);
    d.text(b.machine, g.x + Math.cos(a) * R, g.y + Math.sin(a) * R, d.labPx(9.5), rgba(kind(b), 0.5 * b.ext), c > 0.2 ? "left" : c < -0.2 ? "right" : "center", 300);
  }
  for (const k of sc.tasks) {
    const m = mems.get(k.id);
    if (!k.moving || !m || m.path.length < 2) continue;
    const L = m.cum.at(-1)!, u = Math.min(1, (lastNow - m.t0) / m.dur), head = u * L, tail = Math.min(60, 0.27 * L) * Math.min(1, u + 0.05), col = tierColor(k.model);
    for (let i = 1; i <= 14; i++) {
      const p = along(m.path, m.cum, Math.max(0, head - tail * (1 - (i - 1) / 14))), q = along(m.path, m.cum, Math.max(0, head - tail * (1 - i / 14)));
      cx.strokeStyle = rgba(col, (i / 14) * 0.6);
      cx.lineWidth = ((i / 14) * 2.6) / Math.max(1, dc.ZS * 0.8);
      cx.beginPath();
      cx.moveTo(p.x, p.y);
      cx.lineTo(q.x, q.y);
      cx.stroke();
    }
    const gr = 14 / dc.ZS, gl = cx.createRadialGradient(k.x, k.y, 0, k.x, k.y, gr);
    gl.addColorStop(0, rgba(col, 0.7));
    gl.addColorStop(1, rgba(col, 0));
    cx.globalCompositeOperation = "lighter";
    cx.fillStyle = gl;
    cx.beginPath();
    cx.arc(k.x, k.y, gr, 0, TAU);
    cx.fill();
    cx.globalCompositeOperation = "source-over";
  }
}

