// The Star Map's phase machines (Round 22, concept H): a machine is drawn only while a task uses it, as a branch that grows out of its sun's hub ring,
// takes the first free arc and retracts once no task needs it. A task rides the lines: hub, branch, station, and the Board's curves between suns.
import { bez, textW, type BEdge, type Galaxy, type Pt, type Scene } from "./scene";
import { LABEL, MUTED, PHASE, SUBM, rgba, tierColor, type DrawCtx, type Drawing } from "./draw";
import { glideTime } from "./sky";
import { fitLevel } from "./zoom";

/** Where a task sits on its sun's phase branches: a step of a machine, on the first ring (a phase) or the second (a machine one of those opened). */
export interface HPlace {
  machine: string;
  steps: string[];
  j: number;
  ring1: boolean;
  side?: { machine: string; steps: string[]; j: number };
}
type Node = Pt & { k: string };
/** How much a branch's place gives up to fit: nothing (0), a station on a Board curve (1), its line over a name (2), an arc shared with another branch (3), a station on a name (4). */
type Loose = 0 | 1 | 2 | 3 | 4;
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
  loose?: Loose;
  /** The sun's geometry and the Board's curves and names the branch's place was last checked against. */
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
  /** How far along `path` the dot has ridden: never past the tip of a line still growing. */
  gone: number;
}

const STEP1 = 0.236, D1 = 20, LANE = 28, PAD = 0.06, TAIL = 0.25, GAP = 0.12, CLEAR = 12, OFF = 5, FADE = 0.35, RING = 0.6, BOX = 16, NUDGE = 0.02;
/** Seconds a branch takes to grow out in full, and to retract. */
const GROW = 2, SHRINK = 1.5;
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
/** The arcs a branch at `th` on `lane` holds: its own run (landing, stations, name) and the lanes its spoke or landing crosses on the way out. */
function claims(b: Branch, th: number, lane: number, dir: 1 | -1, angs: number[]): Claim[] {
  const far = angs[angs.length - 1], out: Claim[] = [];
  let from = th - dir * PAD, cross: [number, number] = [th, th], lo = 0;
  if (b.ring === 2) {
    const phi = phiOf(b);
    [from, cross, lo] = [phi - dir * PAD, [phi, phi], branches.get(b.parent!)!.lane + 1];
  }
  const [a0, a1] = [Math.min(from, far + dir * TAIL), Math.max(from, far + dir * TAIL)];
  out.push({ lane, a0, a1 });
  for (let l = lo; l < lane; l++) out.push({ lane: l, a0: Math.min(...cross) - PAD, a1: Math.max(...cross) + PAD });
  return out;
}
const hit = (A: Claim[], B: Claim[]) => A.some((p) => B.some((q) => p.lane === q.lane && clash(p.a0, p.a1, q.a0, q.a1, GAP)));
type Box = { x0: number; y0: number; x1: number; y1: number };
type Spot = { x: number; y: number; align: CanvasTextAlign };
/** Where a step's name prints `R` out from `g` along angle `a`, set to the side the cosine gives. */
function stepSpot(g: Pt, a: number, R: number): Spot {
  const c = Math.cos(a);
  return { x: g.x + Math.cos(a) * R, y: g.y + Math.sin(a) * R, align: c > 0.2 ? "left" : c < -0.2 ? "right" : "center" };
}
const inBox = (p: Pt, n: Box, m: number) => p.x > n.x0 - m && p.x < n.x1 + m && p.y > n.y0 - m && p.y < n.y1 + m;
/** Where a branch at `th` on `lane` sits on the sky: its stations, then its spoke out from the hub (a ring-2 branch's, from its parent's
 *  station). A station may not sit on a Board curve, nor a spoke leave the hub on or run along one leaving this sun; arcs and spokes may cross them. */
function spots(b: Branch, g: Galaxy, th: number, lane: number, angs: number[]): { st: Pt[]; spoke: Pt[] } {
  const r = rad(g, lane), st = angs.map((a) => at(g, r, a, "")), spoke: Pt[] = [];
  const [p, q] = b.ring === 1 ? [at(g, g.edge, th, ""), st[0]] : [at(g, rad(g, branches.get(b.parent!)!.lane), phiOf(b), ""), at(g, r, phiOf(b), "")];
  const m = Math.ceil(Math.hypot(q.x - p.x, q.y - p.y) / 4);
  for (let i = 0; i <= m; i++) spoke.push({ x: p.x + ((q.x - p.x) * i) / m, y: p.y + ((q.y - p.y) * i) / m });
  return { st, spoke };
}
/** Where `b` may be placed: the lowest lane whose stations stay CLEAR of the Board's curves, whose spoke runs along none leaving this sun, whose
 *  line stays off every printed state and hangar name, and whose arc is clear of the sun's other branches. A ring-1 branch stays as near its
 *  preferred angle as it can; a ring-2 branch runs straight out from its parent's station and turns square onto its lane, either way round. */
function fitter(b: Branch, sc: Scene) {
  const g = sc.galaxies[b.sun];
  const base = b.ring === 1 ? 0 : branches.get(b.parent!)!.lane + 1, reach = rad(g, base + LANES + 1) + CLEAR;
  const sample = (e: BEdge, n = 64) => Array.from({ length: n + 1 }, (_, i) => bez(e.p0!, e.c!, e.p1!, i / n)).filter((q) => Math.hypot(q.x - g.x, q.y - g.y) < reach);
  const drawn = sc.bEdges.filter((e) => e.p0 && e.c && e.p1), all = drawn.flatMap((e) => sample(e));
  const docked = drawn.filter((e) => e.source === b.sun || e.target === b.sun).flatMap((e) => sample(e));
  const close = (p: Pt, qs: Pt[]) => qs.some((q) => Math.hypot(p.x - q.x, p.y - q.y) < CLEAR);
  // a spoke crossing a curve is near it for a few samples; one running along it, or leaving the hub on top of it, is near for most
  // the sky the fitted view shows: the scene keeps the canvas's shape, so fitting it to its own size frames what the canvas does
  const v = fitLevel(sc, sc.w, sc.h), view: Box = { x0: -v.x / v.k + BOX, y0: -v.y / v.k + BOX, x1: (sc.w - v.x) / v.k - BOX, y1: (sc.h - v.y) / v.k - BOX };
  const off = (ps: Pt[]) => ps.some((p) => !inBox(p, view, 0));
  const onCurve = ({ st, spoke }: { st: Pt[]; spoke: Pt[] }) => st.some((p) => close(p, all)) || (b.ring === 1 && close(spoke[0], docked)) || spoke.filter((p) => close(p, docked)).length * 4 > 3 * CLEAR;
  const texts = [...sc.names, ...(sc.hangars ?? [])], named = (p: Pt) => texts.some((n) => inBox(p, n, OFF));
  // the arc between its stations and the spoke out to them stay off every printed name too
  const track = ({ st, spoke }: { st: Pt[]; spoke: Pt[] }, lane: number) => {
    const r = rad(g, lane), a0 = b.ring === 1 ? angle(g, st[0]) : angle(g, spoke[spoke.length - 1]), a1 = angle(g, st[st.length - 1]), d = Math.atan2(Math.sin(a1 - a0), Math.cos(a1 - a0));
    const m = Math.max(Math.ceil((Math.abs(d) * r) / 4), 1);
    return [...Array.from({ length: m + 1 }, (_, i) => at(g, r, a0 + (d * i) / m, "")), ...spoke];
  };
  const others = [...branches.values()]
    .filter((o) => o !== b && o.sun === b.sun && !Number.isNaN(o.th) && o.key !== b.parent && o.parent !== b.key)
    .flatMap((o) => claims(o, o.th, o.lane, o.dir, o.at));
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
  /** The station angles a place at `th` gives, or null when it does not fit; a `loose` place may sit on a Board curve (1), and failing that run its
   *  line over a name (2) and then share a lane's arc with another branch (3) and set a station on a name (4), never any of it off the fitted view. */
  const fits = (th: number, lane: number, dir: 1 | -1, loose: Loose = 0): number[] | null => {
    const angs = walk(th, lane, dir), sp = spots(b, g, th, lane, angs);
    // a sub-machine stays out past its parent's lane, which may have moved since it was placed
    const line = track(sp, lane);
    return lane >= base && (loose > 2 || !hit(claims(b, th, lane, dir, angs), others)) && !off([...sp.st, ...line]) && !(loose ? false : onCurve(sp)) && (loose > 3 || !sp.st.some(named)) && (loose > 1 || !line.some(named)) ? angs : null;
  };
  return { base, fits, walk };
}
/** A ring-2 branch looks no further round than this from its parent's station: past it the next lane out is nearer than the arc there. */
const NEAR = 0.6;
/** A branch takes one of this many lanes from its first: rather than go further out it crosses a Board curve, then a name, then shares an arc. */
const LANES = 3;
/** Places `b` once, as near `prefer` as it fits on its lanes; where nothing fits it takes its first lane at `prefer`, so a branch always has a place to grow from. */
function allocate(b: Branch, sc: Scene, prefer: number) {
  const { base, fits, walk } = fitter(b, sc), n = b.ring === 2 ? 2 * Math.round(NEAR / 0.05) + 1 : 2 * Math.ceil(Math.PI / 0.05);
  for (const loose of [0, 1, 2, 3, 4] as const)
    for (let lane = base; lane < base + LANES; lane++)
      for (let i = 0; i <= n; i++) {
        const dir: 1 | -1 = b.ring === 2 && i % 2 ? -1 : 1, k = b.ring === 2 ? Math.floor(i / 2) : Math.ceil(i / 2);
        const th = b.ring === 2 ? prefer + dir * k * 0.05 : prefer + (i % 2 ? 1 : -1) * k * 0.05;
        const angs = fits(th, lane, dir, loose);
        if (angs) return Object.assign(b, { th, lane, dir, at: angs, loose });
      }
  Object.assign(b, { th: prefer, lane: base, dir: 1, at: walk(prefer, base, 1), loose: 4 });
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
/** Where branch node `k` sits this frame, a `+i` spot stacked OFF per dot out from its station included; undefined off every branch. */
function spot(sc: Scene, nodes: Map<string, Node>, k: string): Node | undefined {
  const [base, i] = k.split("+"), s = nodes.get(base);
  if (!s || !i) return s;
  const g = sc.galaxies[base.split("|")[0]], l = Math.hypot(s.x - g.x, s.y - g.y) || 1;
  return { k, x: s.x + ((s.x - g.x) / l) * OFF * +i, y: s.y + ((s.y - g.y) / l) * OFF * +i };
}

/** Each branch drawn at least `min` of the way out (by default in full), with its own line from its landing (or the hub) to its last station:
 *  what the overlap check measures. Siblings share the station they open from, so a ring-2 line starts past it. */
export const branchLines = (min = 1) =>
  [...branches.values()].filter((b) => b.ext >= min && b.route.length).map((b) => ({ key: b.key, sun: b.sun, ring: b.ring, parent: b.parent, th: +b.th.toFixed(3), lane: b.lane, dir: b.dir, n: b.steps.length, pj: b.pj, loose: b.loose, ext: b.ext, pts: b.route.slice(b.own + (b.parent ? 1 : 0)) }));
/** How far `p` sits from the segment a–b. */
function seg(p: Pt, a: Pt, b: Pt) {
  const dx = b.x - a.x, dy = b.y - a.y, l = dx * dx + dy * dy, u = l ? Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / l)) : 0;
  return Math.hypot(a.x + dx * u - p.x, a.y + dy * u - p.y);
}
/** The stretch of a way from `d0` to `d1` along it, every corner between included: a comet's tail bends with the line it rides. */
function stretch(p: Pt[], cum: number[], d0: number, d1: number): Pt[] {
  return [along(p, cum, d0), ...p.filter((_, i) => cum[i] > d0 && cum[i] < d1), along(p, cum, d1)];
}
/** How far back along its way a moving dot's comet tail reaches. */
const tailOf = (m: Mem) => Math.min(60, 0.27 * m.cum.at(-1)!) * Math.min(1, m.gone / m.cum.at(-1)! + 0.05);
/** Whether `b`'s line has grown out past its station `s`. */
function reached(b: Branch, s: number) {
  const own = b.route.slice(b.own), cum = lengths(own);
  return own.length > 1 && b.ext * cum.at(-1)! >= cum[b.st[s] - b.own] - 0.01;
}
/** Each dot on a branch or on its way, bar one stacked out from its station, that sits, or whose comet tail runs, further than `tol` off every
 *  line drawn this frame (a branch's grown line, a hub ring, a Board curve), as `id@node`: what the ride check counts. */
export function offLine(sc: Scene, tol = 2): string[] {
  const lines = [...branches.values()].flatMap((b) => {
    const own = b.route.slice(b.own), cum = lengths(own), reach = b.ext * (cum.at(-1) ?? 0), n = cum.filter((c) => c <= reach).length;
    return own.length < 2 ? [] : [[...own.slice(0, n), along(own, cum, reach)]];
  });
  const curves = sc.bEdges.filter((e) => e.p0 && e.c && e.p1).map((e) => Array.from({ length: 129 }, (_, i) => bez(e.p0!, e.c!, e.p1!, i / 128)));
  const rings = [...new Set([...branches.values()].map((b) => b.sun))].flatMap((s) => (sc.galaxies[s] ? [sc.galaxies[s]] : []));
  // the spur a stacked dot steps out along from its station (stacking is its own design) counts as on the line
  const stations = [...branches.values()].flatMap((b) => b.st.map((i) => b.route[i])), spur = (p: Pt) => stations.some((s) => Math.hypot(p.x - s.x, p.y - s.y) <= 2 * OFF + tol);
  const near = (p: Pt) => spur(p) || [...lines, ...curves].some((l) => l.some((q, i) => i > 0 && seg(p, l[i - 1], q) <= tol)) || rings.some((g) => Math.abs(Math.hypot(p.x - g.x, p.y - g.y) - g.edge) <= tol);
  return sc.tasks.flatMap((k) => {
    const m = mems.get(k.id);
    const stacked = !k.moving && m?.route.at(-1)!.k.includes("+");
    if (!m || !(k.moving || m.node.includes("#")) || m.fade || stacked) return [];
    const tail = k.moving && m.path.length > 1 ? stretch(m.path, m.cum, Math.max(0, m.gone - tailOf(m)), m.gone) : [];
    const mids = tail.slice(1).map((q, i) => ({ x: (q.x + tail[i].x) / 2, y: (q.y + tail[i].y) / 2 }));
    return [k, ...mids].every(near) ? [] : [`${k.id}@${m.node}`];
  });
}
/** The line a dot on a branch rode out to where it is now, from its sun's hub ring through each station it passed, each stretch in its
 *  branch's colour, blended across a change of branch; null for a dot in orbit. */
export function trailOf(id: string, sc: Scene): { pts: (Pt & { c: string; k?: string })[]; stations: (Node & { c: string })[] } | null {
  const m = mems.get(id);
  if (!m || m.node.startsWith("orbit:") || m.route.length < 2) return null;
  // the dot sits on the route's nearest stretch, or past its end while it is still gliding in
  let best = Infinity, cut = m.route.length - 1, end: Pt = m.route[cut];
  for (let i = 1; i < m.route.length; i++) {
    const a = m.route[i - 1], b = m.route[i], dx = b.x - a.x, dy = b.y - a.y, l = dx * dx + dy * dy;
    const u = l ? Math.max(0, Math.min(1, ((m.x - a.x) * dx + (m.y - a.y) * dy) / l)) : 0, q = { x: a.x + dx * u, y: a.y + dy * u }, d = Math.hypot(q.x - m.x, q.y - m.y);
    if (d < best - 0.5) [best, cut, end] = [d, i - 1, q];
  }
  let c = MUTED;
  const run = m.route.slice(0, cut + 1).map((n) => {
    const b = branches.get(n.k.slice(0, n.k.lastIndexOf(":")));
    if (b) c = n.k.endsWith(":h") ? (sc.galaxies[b.sun]?.color ?? c) : kind(b);
    return { ...n, c };
  });
  const pts: (Pt & { c: string; k?: string })[] = [...run, { ...end, c }], cum = lengths(pts), station = (p: { k?: string }) => /:\d+$/.test(p.k ?? "");
  // where the colour changes, it blends over the stretch between the stations either side
  const blended = [...pts];
  for (let j = 1; j < pts.length; j++) {
    if (pts[j].c === pts[j - 1].c) continue;
    const from = Math.max(0, pts.slice(0, j).findLastIndex(station)), next = pts.findIndex((p, i) => i >= j && station(p)), to = next < 0 ? pts.length - 1 : next;
    for (let i = from + 1; i < to; i++) blended[i] = { ...pts[i], c: mix(pts[from].c, pts[to].c, (cum[i] - cum[from]) / (cum[to] - cum[from] || 1)) };
  }
  return { pts: blended, stations: run.filter(station) };
}
const mix = (a: string, b: string, t: number) => {
  const [x, y] = [a, b].map((h) => parseInt(h.slice(1), 16)), u = Math.max(0, Math.min(1, t));
  const ch = (s: number) => Math.round(((x >> s) & 255) * (1 - u) + ((y >> s) & 255) * u);
  return `#${((ch(16) << 16) | (ch(8) << 8) | ch(0)).toString(16).padStart(6, "0")}`;
};
/** The sun's place and size and the Board's curves and names, which a branch's place was checked against. */
function layout(sc: Scene, sun: string) {
  const g = sc.galaxies[sun];
  return [sc.bEdges.length, sc.names.length, sc.hangars?.length ?? 0, Math.round(g.x), Math.round(g.y), Math.round(g.edge)].join();
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
    // a place is kept while it still fits: only once the sun moves or grows, or a curve or name moves onto it, is it checked again, and a branch
    // that no longer fits is placed afresh and grows out again from the hub, its sub-machines and dots with it
    for (const b of branches.values()) {
      if (b.ring !== ring || Number.isNaN(b.th) || !sc.galaxies[b.sun] || (b.parent && !branches.has(b.parent))) continue;
      const ok = layout(sc, b.sun);
      if (b.ok === ok) continue;
      b.ok = ok;
      const angs = fitter(b, sc).fits(b.th, b.lane, b.dir, b.loose);
      if (angs) {
        b.at = angs;
        continue;
      }
      const fam = [b, ...[...branches.values()].filter((o) => o.parent === b.key)];
      for (const o of fam) Object.assign(o, { th: NaN, ext: 0, ok: undefined });
      for (const [id, m] of mems) if (fam.some((o) => m.node.startsWith(`${o.key}#`))) mems.delete(id);
    }
    for (const b of branches.values()) {
      if (b.ring !== ring || !Number.isNaN(b.th) || !sc.galaxies[b.sun]) continue;
      if (b.parent && (!branches.has(b.parent) || Number.isNaN(branches.get(b.parent)!.th))) continue;
      const k = tasks.find((t) => want.get(t.id)?.b === b), m = k && mems.get(k.id), g = sc.galaxies[b.sun];
      const at = ring === 2 ? phiOf(b) : m ? angle(g, m) : NaN;
      allocate(b, sc, Number.isFinite(at) ? at : -Math.PI / 2);
      b.ok = layout(sc, b.sun);
    }
  }
  const kids = new Set([...branches.values()].flatMap((b) => (b.parent ? [b.parent] : [])));
  for (const b of [...branches.values()]) {
    if (!sc.galaxies[b.sun] || (b.parent && !branches.has(b.parent))) {
      branches.delete(b.key);
      continue;
    }
    // a branch grows once it is placed, a sub-machine once its parent's line has reached the station it opens from
    const par = b.parent ? branches.get(b.parent)! : undefined;
    if (b.alive && !Number.isNaN(b.th) && (!par || reached(par, b.pj))) b.ext = Math.min(1, b.ext + dt / GROW);
    else if (!kids.has(b.key)) b.ext -= dt / SHRINK;
    // a branch opened on a frame no time has passed since is still wanted, not retracted
    if (b.ext <= 0 && !b.alive) branches.delete(b.key);
    else if (b.ext < 1) busy = true;
  }
  for (const ring of [1, 2]) for (const b of branches.values()) if (b.ring === ring) shape(b, sc.galaxies[b.sun]);
  // the nodes of each branch's own line its growing tip has not reached yet: a dot rides up to the tip and waits there
  const ahead = new Set<string>();
  for (const b of branches.values()) {
    const own = b.route.slice(b.own), cum = lengths(own), reach = b.ext * (cum.at(-1) ?? 0);
    own.forEach((p, i) => i && cum[i] > reach + 0.01 && ahead.add(p.k));
  }
  const nodes = new Map([...branches.values()].flatMap((b) => b.route.map((p) => [p.k, p] as const)));
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
      const i = stacks.get(`${w.b.key}#${w.j}`)!.indexOf(k.id);
      route = w.b.route.slice(0, w.b.st[w.j] + 1);
      // a later dot on the same station sits OFF further out from the sun per dot, where its label already steps out to
      if (i) route.push(spot(sc, nodes, `${route.at(-1)!.k}+${i}`)!);
      node = `${w.b.key}#${w.j}`;
      bks = w.b.parent ? [w.b.parent, w.b.key] : [w.b.key];
    } else {
      route = [at(g, g.edge, angle(g, k), `orbit:${sun}:h`), { k: `orbit:${sun}:${k.id}`, x: k.x, y: k.y }];
      node = `orbit:${sun}`;
      bks = [];
    }
    let m = mems.get(k.id);
    // a dot first seen on a branch still growing rides out with its tip
    if (!m) mems.set(k.id, (m = { node, route, bks, path: route, cum: lengths(route), t0: now - 9, dur: 0.8, fade: null, x: route.at(-1)!.x, y: route.at(-1)!.y, hold: [], gone: 0 }));
    else if (m.node !== node) {
      const oldSun = m.node.startsWith("orbit:") ? m.node.slice(6) : m.node.split("|")[0], p = travel(sc, oldSun, m.route, sun, route);
      // a dot still gliding keeps to the line: it finishes the rest of its way, dropping any stretch the new way would ride straight back
      const mid = p && !m.fade && m.gone < m.cum.at(-1)! && m.path.length > 1, next = m.cum.findIndex((c) => c > m!.gone);
      const rest = mid ? m.path.slice(next < 1 ? m.path.length - 1 : next) : [], q = p ? [...p] : [];
      while (rest.length >= 2 && q.length >= 2 && rest.at(-2)!.k === q[1].k) {
        rest.pop();
        q.shift();
      }
      const from = m.gone >= m.cum.at(-1)! ? m.route.at(-1)!.k : "cur";
      m.path = p ? [{ k: from, x: m.x, y: m.y }, ...rest.slice(0, -1), ...(rest.length ? q : q.slice(1))] : [route.at(-1)!];
      m.cum = lengths(m.path);
      m.dur = p ? glideTime(m.cum.at(-1)!) : 2 * FADE;
      m.fade = p ? null : { x: m.x, y: m.y };
      m.t0 = now;
      m.gone = 0;
      m.hold = [...new Set([...(mid ? m.hold : []), ...m.bks])];
      [m.node, m.bks] = [node, bks];
    }
    m.route = route;
    // the way follows its branches as they are laid out afresh, and its end follows the place as its branch grows or its orbit turns
    m.path = m.path.map((p) => spot(sc, nodes, p.k) ?? p);
    m.path[m.path.length - 1] = route.at(-1)!;
    if (m.path.length > 1) m.cum = lengths(m.path);
    const u = Math.min(1, (now - m.t0) / m.dur), L = m.cum.at(-1)!, stop = m.path.findIndex((p) => ahead.has(p.k.split("+")[0]));
    m.gone = Math.min(u * L, stop < 0 ? L : m.cum[Math.max(0, stop - 1)]);
    const done = m.fade ? u >= 1 : m.gone >= L;
    let q: Pt = route.at(-1)!, alpha = 1;
    if (m.fade) {
      if (u < 0.5) [q, alpha] = [m.fade, 1 - u * 2];
      else alpha = u * 2 - 1;
    } else if (!done && m.path.length > 1) q = along(m.path, m.cum, m.gone);
    if (done) {
      m.hold = [];
      m.fade = null;
    } else busy = true;
    [m.x, m.y] = [q.x, q.y];
    if (w && !w.b.parent) m.last = { sun, machine: w.b.machine, steps: w.b.steps, j: w.j };
    const i = w ? stacks.get(`${w.b.key}#${w.j}`)!.indexOf(k.id) : 0, age = (now - m.t0 - m.dur) / RING;
    // the dot rides the branch's lines, never the Board hop's curve the frame set up for it
    k.x = q.x;
    k.y = q.y;
    k.hop = undefined;
    k.moving = !done && !m.fade;
    k.alpha = i >= 3 && done ? 0 : alpha;
    k.arrive = w && age >= 0 && age < 1 && now - m.t0 < 9 ? { x: q.x, y: q.y, r: 6, col: "#c084fc", age, grow: 18 } : null;
  }
  for (const id of [...mems.keys()]) if (!tasks.some((k) => k.id === id)) mems.delete(id);
  return busy;
}

/** The live branches and their stations, the step and machine names of each the pointer (`at`) or a hovered dot is on, then the movers' comet
 *  tails, each bending with its line; drawTasks draws the heads. */
export function drawBranches(dc: DrawCtx, d: Drawing, sc: Scene, at: Pt | null) {
  const { cx } = dc, lw = 1.1 / Math.max(1, dc.ZS * 0.8), suns = new Map<string, number>();
  for (const b of branches.values()) suns.set(b.sun, Math.max(suns.get(b.sun) ?? 0, b.ext));
  for (const [sun, e] of suns) {
    const g = sc.galaxies[sun];
    if (g) d.circle(g.x, g.y, g.edge, rgba("#c4b5fd", 0.16 * e), lw);
  }
  const occ = new Map<string, number>();
  for (const m of mems.values()) if (m.node.includes("#")) occ.set(m.node, (occ.get(m.node) ?? 0) + 1);
  const hover = dc.hover?.kind === "task" ? mems.get(dc.hover.o.id)?.bks : undefined, reach = 10 / dc.K;
  const labs: { s: string; t: Spot; px: number; rank: number; n: number; a: number; e: number }[] = [], pins: Pt[] = [];
  for (const b of branches.values()) {
    const g = sc.galaxies[b.sun], own = b.route.slice(b.own), cum = lengths(own), tip = b.ext * cum.at(-1)!;
    if (!g || own.length < 2) continue;
    const line = stretch(own, cum, 0, tip);
    cx.strokeStyle = rgba(kind(b), 0.45 * Math.min(1, b.ext * 2));
    cx.lineWidth = lw;
    cx.beginPath();
    line.forEach((p, i) => (i ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y)));
    cx.stroke();
    const hot = hover?.includes(b.key) || (at && line.some((p, i) => i && seg(at, line[i - 1], p) <= reach));
    b.steps.forEach((name, s) => {
      const p = b.route[b.st[s]], n = occ.get(`${b.key}#${s}`) ?? 0;
      if (cum[b.st[s] - b.own] > tip + 0.01) return;
      if (s <= b.seen) d.dot(p.x, p.y, 2.2 / Math.max(1, dc.ZS * 0.5), rgba(kind(b), 0.85));
      else d.circle(p.x, p.y, 2.2 / Math.max(1, dc.ZS * 0.5), rgba(kind(b), 0.55), lw);
      if (!hot) return;
      pins.push(p);
      // a step's name prints square off its line: outward from an arc, to the branch's side of a ray
      const i = b.st[s], u = b.route[Math.min(i + 1, b.route.length - 1)], v = b.route[Math.max(i - 1, b.own)], r = angle(g, p);
      const a = Math.abs(Math.sin(Math.atan2(u.y - v.y, u.x - v.x) - r)) > 0.7 ? r : r + (b.dir * Math.PI) / 2;
      labs.push({ s: name.replace(/_/g, " "), t: stepSpot(p, a, d.labPx(5)), px: 9, rank: n ? 1 : 2, n, a, e: b.ext });
    });
    if (!hot) continue;
    // a name centred above or below the sun would sit on its own arc, so it moves a line further out
    const end = b.route.at(-1)!, a = angle(g, end) + b.dir * 0.12, R = Math.hypot(end.x - g.x, end.y - g.y) + (Math.abs(Math.cos(a)) <= 0.2 ? d.labPx(9.5) : 0);
    labs.push({ s: b.machine, t: stepSpot(g, a, R), px: 9.5, rank: 0, n: 0, a, e: b.ext });
  }
  // names print machine first, then occupied steps, each only where it clears every name and station already down
  const taken: Box[] = [];
  for (const l of labs.sort((x, y) => x.rank - y.rank)) {
    const h = d.labPx(l.px), w = (textW(l.s, l.px) * h) / l.px, x0 = l.t.align === "left" ? l.t.x : l.t.align === "right" ? l.t.x - w : l.t.x - w / 2;
    const box = { x0, y0: l.t.y - h / 2, x1: x0 + w, y1: l.t.y + h / 2 };
    if (taken.some((o) => box.x0 < o.x1 && o.x0 < box.x1 && box.y0 < o.y1 && o.y0 < box.y1) || pins.some((p) => inBox(p, box, h / 4))) continue;
    taken.push(box);
    d.text(l.s, l.t.x, l.t.y, h, rgba(LABEL, 0.85 * l.e), l.t.align, 300);
    if (l.n > 3) d.text(`+${l.n - 3}`, l.t.x + Math.cos(l.a) * h * 4, l.t.y + Math.sin(l.a) * h * 4, d.labPx(8), rgba(LABEL, 0.6 * l.e));
  }
  for (const k of sc.tasks) {
    const m = mems.get(k.id);
    if (!k.moving || !m || m.path.length < 2) continue;
    const head = m.gone, tail = tailOf(m), col = tierColor(k.model);
    for (let i = 1; i <= 14; i++) {
      const piece = stretch(m.path, m.cum, Math.max(0, head - tail * (1 - (i - 1) / 14)), Math.max(0, head - tail * (1 - i / 14)));
      cx.strokeStyle = rgba(col, (i / 14) * 0.6);
      cx.lineWidth = ((i / 14) * 2.6) / Math.max(1, dc.ZS * 0.8);
      cx.beginPath();
      piece.forEach((p, j) => (j ? cx.lineTo(p.x, p.y) : cx.moveTo(p.x, p.y)));
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
