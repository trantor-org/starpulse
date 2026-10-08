// The geometry of the level above the Board: the orbit card of the approved hub mockup (design/hub, Mock C), pure.
// Every source follows one closed rose curve with a petal round each sun: one sun is a circle, two a lemniscate, three a
// trefoil, four a clover. A petal is walked by arc length, so a source keeps one speed along it, and the share of a
// period spent in a petal is half its share of the source's runs and half its length, so dwell grows with the share
// while a petal nobody reaches is still crossed at no more than about twice the average speed.
import { BOARD_COLOR, TAU, type Pt } from "../../render/scene";

/** Whether the suns are the terminals (where runs end) or the working states (where runs spend their time). */
export type SunMode = "terminal" | "working";

export interface Drift {
  added: string[];
  removed: string[];
}

export interface OrbitSourceIn {
  id: string;
  name: string;
  /** A forwarder named it: it draws its own Board; an unnamed one only counts in the aggregate. */
  shared: boolean;
  wip: number;
  /** Runs it ends a day over the window, which sets how fast it circles. */
  perDay: number;
  /** Mean working days a run it ended spent, which sets how far its petals reach. */
  cycleDays: number;
  ended: Record<string, number>;
  terminalShare: Record<string, number>;
  timeShare: Record<string, number>;
  drift?: Drift;
}

export interface OrbitInput {
  suns: SunMode;
  /** Every way a run ends, in config order. */
  terminals: { id: string; role: string }[];
  /** The working states, in lifecycle order. */
  working: string[];
  name: (state: string) => string;
  endedTotals: Record<string, number>;
  taskDays: Record<string, number>;
  sources: OrbitSourceIn[];
  /** The canvas's width over its height: the scene is as wide as the canvas is. */
  aspect: number;
}

export interface Sun extends Pt {
  id: string;
  name: string;
  role: string;
  col: string;
  r: number;
  /** The angle on the ring, from the centre. */
  phi: number;
  /** Runs that ended here, or task-days spent here. */
  n: number;
}

interface Arc {
  pts: Pt[];
  /** Cumulative length at each sample over the petal's whole length. */
  L: number[];
  len: number;
}

export interface OrbitBody {
  src: OrbitSourceIn;
  id: string;
  name: string;
  col: string;
  /** Its share of each sun, by sun id: where its runs end, or where they spend their time. */
  w: Record<string, number>;
  /** Its share of the period spent in each petal, by sun index. */
  frac: number[];
  scale: number;
  period: number;
  phase: number;
  r: number;
  path: number[];
  arc: Arc[];
  /** Where the planet is now, written by the drawer each frame: what a hover and a click find. */
  x: number;
  y: number;
}

export interface OrbitScene {
  w: number;
  h: number;
  c: Pt;
  suns: Sun[];
  /** The bodies runs end in: the suns themselves, or the column beside the working orbit. */
  ends: Sun[];
  sources: OrbitBody[];
  box: [number, number, number, number];
}

export const TERM_COL: Record<string, string> = { abandoned: "#fb7185", parked: "#fbbf24", blocked: "#c4b5fd" };
const PALETTE = ["#a78bfa", "#67e8f9", "#f472b6", "#fbbf24", "#34d399", "#fb923c"];
const UNNAMED = "#94a3b8";
const ARC_N = 400;
const PATH_N = 720;
/** Four times, less a margin, in the bound on how fast one petal is crossed against another: 1 + λ / ((1 - λ)ℓ) <= 3.9. */
const BLEND = 2.9;

/** The petal geometry for N suns, as a rose curve r = A cos(m(θ - φ))^p traces it. */
export function petals(N: number): { hw: number; m: number; p: number; order: number[]; dir: number[] } {
  if (N === 2) return { hw: Math.PI / 4, m: 2, p: 0.5, order: [0, 1], dir: [1, -1] };
  const odd = N % 2 === 1, hw = odd ? Math.PI / (2 * N) : Math.PI / N, step = odd ? (N + 1) / 2 : 1 + N / 2, order: number[] = [];
  for (let k = 0, j = 0; k < N; k++, j = (j + step) % N) order.push(j);
  return { hw, m: Math.PI / (2 * hw), p: odd ? 0.35 : 0.45, order: new Set(order).size === N ? order : [...Array(N).keys()], dir: order.map(() => 1) };
}

const terminalColor = (t: { id: string; role: string }) => (t.role === "goal" ? BOARD_COLOR[t.id] : TERM_COL[t.role]) ?? UNNAMED;

/** The raw petal: v in [0, 1] sweeps petal i of the orbit by angle, which races through the centre. */
function petalAt(scene: Pick<OrbitScene, "c" | "suns">, b: Pick<OrbitBody, "w" | "scale">, P: ReturnType<typeof petals>, i: number, v: number): Pt {
  const { c, suns } = scene, k = P.order[i], sun = suns[k];
  const th = P.dir[i] * (-P.hw + v * 2 * P.hw), D = Math.hypot(sun.x - c.x, sun.y - c.y), A = D * (1.35 + 0.55 * (b.w[sun.id] ?? 0)) * b.scale;
  const rr = A * Math.pow(Math.max(0, Math.cos(P.m * th)), P.p), a = sun.phi + th;
  return { x: c.x + Math.cos(a) * rr, y: c.y + Math.sin(a) * rr };
}

/** Each petal sampled densest at the centre (where r grows as θ^p), so interpolating by distance keeps one speed along it. */
function arcs(scene: Pick<OrbitScene, "c" | "suns">, b: Pick<OrbitBody, "w" | "scale">): Arc[] {
  const P = petals(scene.suns.length);
  return P.order.map((_, i) => {
    const pts: Pt[] = [], L = [0];
    for (let j = 0; j <= ARC_N; j++) {
      const t = j / ARC_N, e = 0.5 - 0.5 * Math.sign(1 - 2 * t) * Math.pow(Math.abs(1 - 2 * t), 1 / P.p);
      pts.push(petalAt(scene, b, P, i, e));
      if (j) L.push(L[j - 1] + Math.hypot(pts[j].x - pts[j - 1].x, pts[j].y - pts[j - 1].y));
    }
    return { pts, L: L.map((l) => l / L[ARC_N]), len: L[ARC_N] };
  });
}

/** The point on a source's orbit at u in [0, 1): the petal u falls in by the source's shares, in visiting order, then the walk along it. */
export function positionAt(scene: Pick<OrbitScene, "c" | "suns">, b: OrbitBody, u: number): Pt & { k: number } {
  const S = scene.suns, N = S.length;
  if (N === 1) {
    const R = 150 * b.scale, a = u * TAU;
    return { x: S[0].x + Math.cos(a) * R, y: S[0].y + Math.sin(a) * R, k: 0 };
  }
  const P = petals(N);
  let i = 0, acc = 0;
  while (i < N - 1 && u >= acc + b.frac[P.order[i]]) acc += b.frac[P.order[i++]];
  const v = Math.min(1, Math.max(0, (u - acc) / b.frac[P.order[i]])), { pts, L } = b.arc[i];
  let lo = 0, hi = ARC_N;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (L[mid] <= v) lo = mid;
    else hi = mid;
  }
  const f = (v - L[lo]) / (L[hi] - L[lo] || 1);
  return { x: pts[lo].x + (pts[hi].x - pts[lo].x) * f, y: pts[lo].y + (pts[hi].y - pts[lo].y) * f, k: P.order[i] };
}

/** How fast a source goes along each petal, in scene units per period: the mockup holds the fastest to at most four times the slowest. */
export function petalSpeeds(b: OrbitBody): number[] {
  const P = petals(b.arc.length);
  return b.arc.length < 2 ? [] : b.arc.map((a, i) => a.len / b.frac[P.order[i]]);
}

const sunBody = (id: string, name: string, role: string, col: string, n: number, r: number, at: Pt & { phi: number }): Sun => ({ id, name, role, col, n, r, ...at });

/** Where everything on the level sits for a canvas of the given aspect, from the level's numbers alone. */
export function layoutOrbit(input: OrbitInput): OrbitScene {
  const w = Math.max(1860, Math.round(950 * input.aspect)), h = Math.round(w / input.aspect), c = { x: w / 2, y: h * 0.5 };
  const work = input.suns === "working";
  // the goal first: with N suns on a ring, N petals apart, one sun is the centre and two face each other
  const terms = [...input.terminals].sort((a, b) => Number(b.role === "goal") - Number(a.role === "goal"));
  const ring = work ? input.working.filter((id) => !terms.some((t) => t.id === id)).map((id) => ({ id, role: "working" })) : terms;
  const N = ring.length, D = N === 1 ? 0 : N === 2 ? h * 0.17 : h * 0.2;
  const termSun = (t: { id: string; role: string }, at: Pt & { phi: number }) => {
    const n = input.endedTotals[t.id] ?? 0;
    return sunBody(t.id, input.name(t.id), t.role, terminalColor(t), n, 16 + 2.6 * Math.sqrt(n), at);
  };
  const suns = ring.map((t, i) => {
    const phi = Math.PI + (i * TAU) / N, at = { phi, x: c.x + Math.cos(phi) * D, y: c.y + Math.sin(phi) * D };
    if (!work) return termSun(t, at);
    const days = input.taskDays[t.id] ?? 0;
    return sunBody(t.id, input.name(t.id), "working", BOARD_COLOR[t.id] ?? UNNAMED, days, 14 + 1.5 * Math.sqrt(days), at);
  });
  // working suns: the terminals stand in a column right of the orbits, the goal on top, the bodies runs leave the orbit for
  const ends = work ? terms.map((t, i) => termSun(t, { phi: 0, x: c.x + 3.4 * D + 120, y: c.y + (i - (terms.length - 1) / 2) * 230 })) : suns;
  const scene: OrbitScene = { w, h, c, suns, ends, sources: [], box: [0, 0, w, h] };

  const cycles = input.sources.map((s) => s.cycleDays), lo = Math.min(...cycles), hi = Math.max(...cycles, lo + 1);
  const maxDay = Math.max(...input.sources.map((s) => s.perDay), 0.1);
  scene.sources = input.sources.map((src, i) => {
    const wt = work ? src.timeShare : src.terminalShare, ws = ring.map((t) => 0.06 + (wt[t.id] ?? 0)), W0 = ws.reduce((a, x) => a + x, 0);
    const b: OrbitBody = {
      src, id: src.id, name: src.name, col: src.shared ? PALETTE[i % PALETTE.length] : UNNAMED, w: wt,
      frac: ws.map((x) => x / W0), scale: 1 + 0.35 * ((src.cycleDays - lo) / (hi - lo)),
      period: 70 / (0.6 + 0.6 * (src.perDay / maxDay)), phase: i / input.sources.length, r: 12 + 2 * Math.sqrt(src.wip), path: [], arc: [], x: 0, y: 0,
    };
    if (N > 1) {
      b.arc = arcs(scene, b);
      const P = petals(N), len = ring.map(() => 0);
      P.order.forEach((k, j) => (len[k] = b.arc[j].len));
      const L0 = len.reduce((a, x) => a + x, 0), got = ring.reduce((a, t) => a + (wt[t.id] ?? 0), 0);
      // The mockup's half-and-half blend crosses a petal nobody reaches at up to 1 / (1 - λ) times the average speed and one
      // everybody reaches at ℓ / ((1 - λ)ℓ + λ) times it, ℓ being its share of the length: the ratio 1 + λ / ((1 - λ)ℓ). λ is
      // capped to keep that under four whatever the shares, which only bites with four suns. A source with no runs to share
      // spends its period by length alone.
      const shortest = Math.min(...len) / L0, lambda = got ? Math.min(0.5, (BLEND * shortest) / (1 + BLEND * shortest)) : 0;
      b.frac = ring.map((t, k) => (1 - lambda) * (len[k] / L0) + (got ? (lambda * (wt[t.id] ?? 0)) / got : 0));
    }
    for (let k = 0; k <= PATH_N; k++) {
      const q = positionAt(scene, b, k / PATH_N);
      b.path.push(q.x, q.y);
    }
    return b;
  });

  const xs = scene.sources.flatMap((b) => b.path.filter((_, j) => j % 2 === 0)), ys = scene.sources.flatMap((b) => b.path.filter((_, j) => j % 2 === 1));
  scene.box = [Math.min(...xs) - 260, Math.min(...ys) - 110, Math.max(...xs) + 260, Math.max(...ys) + 110];
  if (work) {
    // the box reaches as far left as right so the column fits beside the orbit; the column stands a fixed offset clear of the widest orbit
    const rmax = Math.max(...ends.map((e) => e.r)), half = Math.max(c.x - Math.min(...xs), Math.max(...xs, ...suns.map((u) => u.x + u.r + 160)) - c.x), R = half + 200 + 2 * rmax + 140;
    const ey = ends.flatMap((e) => [e.y - e.r * 2, e.y + e.r + 60]);
    scene.box = [c.x - R, Math.min(...ys, ...ey) - 110, c.x + R, Math.max(...ys, ...ey) + 110];
    for (const e of ends) e.x = c.x + half + 200 + rmax;
  }
  return scene;
}

export interface LabelRect {
  /** Centre. */
  x: number;
  y: number;
  w: number;
  h: number;
}

/** How far down each label moves so none overprints another: a label meeting an earlier one drops below it. */
export function separateLabels(rects: LabelRect[]): number[] {
  const off = rects.map(() => 0);
  const hit = (a: LabelRect, ay: number, b: LabelRect, by: number) => Math.abs(a.x - b.x) < (a.w + b.w) / 2 && Math.abs(ay - by) < (a.h + b.h) / 2;
  rects.forEach((r, i) => {
    let y = r.y, moved = true;
    while (moved) {
      moved = false;
      for (let j = 0; j < i; j++)
        if (hit(r, y, rects[j], rects[j].y + off[j])) {
          y = rects[j].y + off[j] + (r.h + rects[j].h) / 2 + 0.5;
          moved = true;
        }
    }
    off[i] = y - r.y;
  });
  return off;
}
