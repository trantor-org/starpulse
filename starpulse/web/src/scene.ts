// Where everything on a level sits, ported from the approved round-13 mockup
// (the design mockup): the Board's states as galaxies with the
// DAGs as step-graph glyphs beside them, a state's lifecycle system as planets
// round its machine, one machine's states, the DAGs level, and a fold of DAGs over the Board path they write.
import type { Fold, Level } from "./levels";
import { countText, daily, HOUR, stateCount, type Move, type Moves, type Sky } from "./sky";
import type { Dag, DagStep, RawAgent, Transition, Writer } from "./types";

export const TAU = Math.PI * 2;
export const BOARD_COLOR: Record<string, string> = { new: "#94a3b8", ready: "#60a5fa", waiting: "#fbbf24", blocked: "#fb7185", in_progress: "#a78bfa",
  review: "#e879f9", needs_attention: "#64748b", done: "#34d399", completed: "#2dd4bf", archived: "#475569" };
/** Where a task's lifecycle ends, drawn as a black hole: a final Board state. Done is not one (the sweep moves it on to Completed), nor is a
 *  nested machine's final state, which hands its task back to the state that runs the machine. */
export const terminal = (s: { final: boolean; flow?: string }) => s.final && !s.flow;
export const RAMP = ["#94a3b8", "#60a5fa", "#818cf8", "#a78bfa", "#c084fc", "#e879f9", "#f472b6", "#fbbf24", "#34d399"];

export interface Pt {
  x: number;
  y: number;
}
export interface Curve {
  p0: Pt;
  c: Pt;
  p1: Pt;
}
export interface GNode extends Pt {
  name: string;
  status: string;
}
export interface Glyph {
  nodes: GNode[];
  links: [GNode, GNode][];
  w: number;
  h: number;
  br: number;
}
/**
 * A Board DAG's one tether, drawn only while it is hovered: to the middle of the path carrying most of its criteria, else to the state it sits
 * beside. A cue is a looser tie than a write, so a tether made only of cues is fainter. `crit` is the hover's list of every criterion.
 */
export interface Tether extends Pt {
  edge?: BEdge;
  /** The body the tether ends on the rim of: a Board state's galaxy, or a state level's primary or moon. */
  g?: Pt & { R: number; id?: string };
  cue: boolean;
  crit: string[];
}
export interface Star extends Dag, Pt {
  /** The name drawn under it: a DAG's bare name when no other instance runs one by that name, else `<instance>/<name>`. */
  label: string;
  glyph: Glyph;
  br: number;
  group: string;
  runnable: boolean;
  tether?: Tether;
  /** A body that stands for several DAGs on one path (or beside one state): the DAGs it folds, in name order. */
  fold?: string[];
  /** The skill machine a state level's launch-only DAG orbits. */
  owned?: Planet;
}
/** Every DAG that writes no Board lane and is no cue, folded into one body at the right end of the axis. */
export interface Hangar extends Pt {
  r: number;
  names: string[];
  doms: number;
}
/** Anything tasks orbit: a Board state, a state level's sun, or a lifecycle machine. */
export interface Host extends Pt {
  name: string;
  R: number;
  r?: number;
  color?: string;
  rim?: number;
  rings?: number[];
  states?: Record<string, MState>;
  /** The Board state a moon or sub-state belongs to; its tasks stay with that state while the state holds them. */
  parent?: Galaxy;
}
export interface Galaxy extends Host {
  id: string;
  r: number;
  /** Its count (`stateCount`): on a starting state the day's arrivals, drawn where they went; on any other its tasks, and on a terminal state the day's arrivals there too. */
  n: number;
  /** On a starting or terminal state, the day's arrivals there; absent on any other. */
  today?: number;
  color: string;
  final: boolean;
  subs: string[];
  moonR: number;
  visR: number;
  lab: Pt;
  /** The events that take the state back to itself: drawn nowhere, listed in the state's tooltip, as a machine level lists them. */
  loops: string[];
  /** How far the state's moon names reach right and left of its centre. */
  reach: [number, number];
}
/** A lifecycle machine of a Board state: a still moon in a label row on the state's dashed ring. */
export interface Moon extends Host {
  parent: Galaxy;
  /** The machine's name past its sub-state chain: `machine › sub-state · sub-state`. */
  label: string;
  /** Tasks working the machine outside its sub-states. */
  n: number;
  nStates: number;
  /** How far the sub-state chain runs out past the moon's own orbits. */
  ext: number;
  chain: SubState[];
  /** A paging control standing in for the lifecycle machines not drawn on this page. */
  pager?: Pager;
}
/** A state of a machine that opens a child machine, drawn in its machine's row beside the moon. */
export interface SubState extends Host {
  parent: Galaxy;
  machine: string;
  state: string;
  /** The child machine the state opens, and when it runs. */
  flow: string;
  when: string;
  n: number;
  /** The body before it in the row: the moon, or the sub-state ahead of it. */
  prev: Host;
}
export interface Sun extends Host {
  id: string;
  final: boolean;
  r: number;
  /** Its count (`stateCount`): on a starting state the day's arrivals, drawn where they went; on any other its tasks, and on a terminal state the day's arrivals there too. */
  n: number;
  /** On a starting or terminal state, the day's arrivals there; absent on any other. */
  today?: number;
  color: string;
}
export interface MState extends Pt {
  id: string;
  name: string;
  final: boolean;
  initial: boolean;
  flow: string;
  n: number;
  color: string;
  mini?: boolean;
  /** The events that take the state back to itself: drawn nowhere, listed in the state's tooltip. */
  loops: string[];
  dx?: number;
  dy?: number;
  lab?: Pt;
}
export interface MEdge extends Transition {
  flow: string;
  a?: MState;
  b?: MState;
}
export interface Planet extends Host {
  primary: boolean;
  states: Record<string, MState>;
  edges: MEdge[];
  n: number;
  outer?: number;
  anchor?: MState;
  when?: string;
  /** A skill machine of a state level: a small named body in a row beside the primary, not a planet of its own. */
  moon?: boolean;
  /** A state of a skill machine that opens a child machine: a small body in its machine's row, named `machine>state`. */
  subState?: boolean;
  machine?: string;
  state?: string;
  /** The child machine a sub-state opens and when it runs, and the name it shows. */
  flow?: string;
  title?: string;
  /** A moon's sub-states, outward along its row, and the name drawn past them: `machine › sub-state · sub-state`. */
  chain?: Planet[];
  label?: string;
  /** How far the chain runs out past the moon's own orbits. */
  ext?: number;
  /** How many launch-only DAGs orbit the moon. */
  owned?: number;
  /** The body before this one in its row: the moon, or the sub-state ahead of it. */
  prev?: Planet;
  /** A paging control standing in for the lifecycle machines not drawn on this page. */
  pager?: Pager;
}
/** One of a paged state's two pager nodes: back (d -1) or forward (d 1), standing in for the hidden machines its turn reaches sooner. */
export interface Pager {
  sid: string;
  page: number;
  pages: number;
  d: -1 | 1;
  hidden: string[];
  title: string;
}
/** One Board path per ordered pair of states: every event between them, and every writer with the event it writes. */
export const merged = (trs: Transition[], writers: Record<string, Writer[]>): BEdge[] => {
  const by = new Map<string, BEdge>();
  for (const t of trs) {
    const k = `${t.source}>${t.target}`, m = by.get(k) ?? { source: t.source, target: t.target, event: "", events: [], writers: [] };
    by.set(k, m);
    m.events.push(t.event);
    for (const w of writers[t.event] || []) m.writers.push({ ...w, event: t.event });
  }
  return [...by.values()].map((m) => ({ ...m, event: m.events.join(" · ") }));
};
/** A Board transition: a curve between two galaxies, a self-transition (never drawn), or a path off a state level's screen edge. */
export interface BEdge extends Transition, Partial<Curve> {
  /** Every event between its two states, in that direction; `event` joins them for the hover. */
  events: string[];
  /** Every writer of those events, with the event it writes. */
  writers: (Writer & { event: string })[];
  /** A stay in one state: never drawn, only kept to name its writers' criteria. */
  loop?: boolean;
  busy?: boolean;
  lab?: { name: string; x: number; y: number };
}
export interface Hop extends Curve {
  from: string;
  to: string;
  back: boolean;
  busy?: boolean;
}
export interface Arrive extends Pt {
  r?: number;
  col: string;
  age: number;
}
/** A task orbiting its host; update() places it each frame. */
export interface Body extends RawAgent {
  host: Host;
  R: number;
  a0: number;
  w: number;
  big: boolean;
  x: number;
  y: number;
  ang: number;
  moving: boolean;
  arrive: Arrive | null;
  gone: boolean;
  via: string | null;
  hop?: { c: Curve; u: number };
  bev: Move[];
}
/** A task a lifecycle machine placed, drawn on the state its latest event left it in. */
export interface MachineTask extends RawAgent {
  flow: string;
  _x?: number;
  _y?: number;
  _state?: string;
}
export interface StarGroup {
  name: string;
  head?: boolean;
  lx: number;
  ly: number;
  stars: Star[];
}
/** A Board state at one end of a fold's path. */
export interface FoldEnd extends Pt {
  id: string;
  name: string;
  final: boolean;
  color: string;
  r: number;
}
/** A fold's level: the path between two Board states with its events marked, and a tie from each DAG to every event it writes or runs beside. */
export interface FoldView {
  a?: FoldEnd;
  b?: FoldEnd;
  p0?: Pt;
  p1?: Pt;
  events: (Pt & { name: string })[];
  ties: (Pt & { dag: string; ev: string; cue: boolean })[];
}
export interface Scene {
  w: number;
  h: number;
  /** The Board cut its moon names to NAME_MAX: pages of MIN_PAGE still left its sky too wide. */
  clipped?: boolean;
  /** Sky units a screen pixel the Board's names and rows were laid out at, set once its sky outgrew BOARD_GROW times its base: past that the
   *  sky zooms out, so they shrink on screen with it rather than stay a fixed size. */
  unit?: number;
  galaxies: Record<string, Galaxy>;
  bEdges: BEdge[];
  tasks: Body[];
  machineTasks: MachineTask[];
  mStates: Record<string, MState>;
  mEdges: MEdge[];
  planets: Planet[];
  moons: Moon[];
  subStates: SubState[];
  stars: Record<string, Star>;
  groups: StarGroup[];
  sun: Sun | null;
  flow: string | null;
  hub: Host | null;
  hops: Hop[];
  entries: BEdge[];
  exits: BEdge[];
  box?: [number, number, number, number];
  sid?: string;
  hostAt?: (id: string, t: number) => string;
  /** The bodies a state level's task moved through, each with the time it got there: its back trace. */
  hostTrail?: (id: string) => { at: number; host: string }[];
  /** A line of type's height in world units at the state level's fit zoom. */
  moonLH?: number;
  hangar?: Hangar;
  fold?: FoldView;
}
export interface Ctx {
  S: Sky;
  moves: Moves;
  /** The canvas size the level is laid out for. */
  W: number;
  H: number;
  /** The page clock, in seconds. */
  T: number;
  /** The selected zero-based machine page for each Board state. */
  pages?: Record<string, number>;
  /** The value a layout value `v` named `key` shows: the renderer eases it from the value it showed when a snapshot changes it. The layout
   *  computes its targets from the true sizes, so an eased value never moves another's target. */
  ease?: (key: string, v: number) => number;
  /** Each bent Board path's last bend (`x` along source → target, `y` across it, as fractions of its length), kept by the renderer from one
   *  Board to the next so a path keeps its route while that still clears (routed). */
  routes?: Map<string, Pt>;
}

export const bez = (p0: Pt, c: Pt, p1: Pt, t: number): Pt => {
  const u = 1 - t;
  return { x: u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y: u * u * p0.y + 2 * u * t * c.y + t * t * p1.y };
};
export const curveOf = (a: Pt, b: Pt): Curve => {
  const dx = b.x - a.x, dy = b.y - a.y;
  return { p0: a, p1: b, c: { x: (a.x + b.x) / 2 - dy * 0.15, y: (a.y + b.y) / 2 + dx * 0.15 } };
};
export const sample = (e: Curve, n = 26) => Array.from({ length: n + 1 }, (_, i) => bez(e.p0, e.c, e.p1, i / n));
/** The distance from a point to a curve, measured to 40 straight pieces of it. Hover runs it on every path each frame, so it allocates nothing. */
export const curveDist = ({ p0, c, p1 }: Curve, x: number, y: number) => {
  let d = Infinity, px = p0.x, py = p0.y;
  for (let i = 1; i <= 40; i++) {
    const t = i / 40, u = 1 - t, qx = u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, qy = u * u * p0.y + 2 * u * t * c.y + t * t * p1.y;
    const dx = qx - px, dy = qy - py, L = dx * dx + dy * dy || 1, s = Math.max(0, Math.min(1, ((x - px) * dx + (y - py) * dy) / L));
    d = Math.min(d, Math.hypot(px + s * dx - x, py + s * dy - y));
    px = qx;
    py = qy;
  }
  return d;
};
/** The item nearest the point that lies closer than `band`, the first of equals; null when none does. */
export const nearestWithin = <T>(items: Iterable<T>, dist: (t: T) => number, band: number): T | null => {
  let best: T | null = null, bd = band;
  for (const t of items) {
    const d = dist(t);
    if (d < bd) [bd, best] = [d, t];
  }
  return best;
};
export const textW = (s: string, size: number) => s.length * size * 0.56 + 6;
/** A moon's name as printed on a crowded Board (`Scene.clipped`): past NAME_MAX characters it ends in an ellipsis, so a name reaches only so far toward the next state. */
export const NAME_MAX = 10;
export const clip = (s: string) => (s.length > NAME_MAX ? `${s.slice(0, NAME_MAX - 1)}…` : s);

/** The tethers the page draws: a DAG's own while it is hovered, and none at rest. */
export const tethersDrawn = (scene: Scene, hovered: Star | null): [Star, Tether][] =>
  Object.values(scene.stars).filter((s) => s === hovered && s.tether).map((s): [Star, Tether] => [s, s.tether!]);
/** The events a machine takes from one of its states back to the same state. */
const loopsOf = (flow: { machine: { transitions: Transition[] } }, id: string) => flow.machine.transitions.filter((t) => t.source === id && t.target === id).map((t) => t.event);
/** A Board state's radius: GALAXY_MIN with no tasks, growing with the square root of its count to GALAXY_MAX, which it reaches near 450 tasks. */
export const GALAXY_MIN = 34, GALAXY_MAX = 140;
const galaxyR = (n: number) => Math.min(GALAXY_MAX, GALAXY_MIN + 5 * Math.sqrt(n));
/**
 * A machine state's radius from its task count, growing with its square root to a fixed maximum (near 150 tasks on a machine level, 55 inside
 * a planet).
 */
export const stateR = (s: MState) => (s.mini ? Math.min(12, 3 + 1.2 * Math.sqrt(s.n)) : Math.min(40, 10 + 2.4 * Math.sqrt(s.n)));
/** The `k`th task on a machine state's orbit of radius `R`: rings of tasks 8 apart, each ring 7 further out and turned a little. */
export const taskSlot = (R: number, k: number) => {
  const per = Math.max(8, Math.floor((TAU * R) / 8)), ring = Math.floor(k / per);
  return { t: ((k % per) / per) * TAU - Math.PI / 2 + ring * 0.2, rr: R + ring * 7 };
};
const boxOf = (pts: number[][]): [number, number, number, number] => [
  Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[1])),
];
interface Cand {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  lx?: number;
  ly: number;
}
/** The side of a node for its label that crosses the fewest drawn paths: each candidate is a text rectangle scored against sampled curve points. */
function bestSide(cands: Cand[], pts: Pt[]): Cand {
  let best = cands[0], bs = Infinity;
  for (const c of cands) {
    const s = pts.filter((p) => p.x > c.x0 && p.x < c.x1 && p.y > c.y0 && p.y < c.y1).length;
    if (s < bs) [bs, best] = [s, c];
  }
  return best;
}

/**
 * Where each Board state sits, in the units of the approved mockup: slots along the lifecycle axis (337 apart) and lanes off it. The main line
 * (declared beside the Board machine, since the transitions cannot tell Review from Waiting) takes every other slot in order. Any other open
 * state takes the slot just before the latest main-line state it connects to, and final states one slot past the axis; a slot's states
 * alternate above and below the axis in declaration order, and empty slots close up.
 */
export const AXIS_Y = 675;
export function boardPlaces(states: { id: string; final: boolean }[], transitions: Transition[], mainLine?: string[]): Record<string, [number, number]> {
  const known = (mainLine ?? []).filter((id) => states.some((s) => s.id === id)), axis = known.length ? known : states.map((s) => s.id);
  const col: Record<string, number> = {}, slots: Record<number, string[]> = {}, last = 2 * axis.length - 1, P: Record<string, [number, number]> = {};
  axis.forEach((id, i) => (col[id] = 2 * i));
  for (const st of states)
    if (!(st.id in col)) {
      const near = transitions.flatMap((t) => (t.source === st.id ? [t.target] : t.target === st.id ? [t.source] : [])).filter((n) => n in col);
      (slots[st.final || !near.length ? last : Math.max(...near.map((n) => col[n])) - 1] ||= []).push(st.id);
    }
  const used = [...new Set([...Object.values(col), ...Object.keys(slots).map(Number)])].sort((a, b) => a - b), x = (k: number) => 300 + used.indexOf(k) * 337;
  for (const id of axis) P[id] = [x(col[id]), AXIS_Y];
  for (const [k, ids] of Object.entries(slots))
    ids.forEach((id, j) => (P[id] = [x(+k), AXIS_Y + (j % 2 ? 1 : -1) * (+k === last ? 415 : 255) * (1 + Math.floor(j / 2) * 0.6)]));
  return P;
}

/**
 * How far each state moves right so that no state reaches the next one beside it: it, and every state right of it, moves over until `gap` clears.
 * A state reaches `reach(state, +1)` to its right and `reach(state, -1)` to its left (its moon names go past its rim), its rim by default.
 */
export function separate<T extends Pt & { R: number }>(states: T[], gap: (a: T, b: T) => number, reach: (g: T, side: 1 | -1) => number = (g) => g.R): Map<T, number> {
  const gs = [...states].sort((a, b) => a.x - b.x), dx = new Map(gs.map((g) => [g, 0]));
  for (const b of gs) {
    const need = Math.max(0, ...gs.filter((a) => a.x < b.x - 1 && Math.abs(a.y - b.y) < a.R + b.R + 40)
      .map((a) => a.x + dx.get(a)! + reach(a, 1) + gap(a, b) - (b.x + dx.get(b)! - reach(b, -1))));
    if (need > 0) for (const g of gs) if (g.x >= b.x - 1) dx.set(g, dx.get(g)! + need);
  }
  return dx;
}

/** A sun's radius: `min` until its `n` tasks, `gap` apart on the ring `pad` outside it, would need a second ring; past that, the radius that holds them in one. */
export const oneRing = (n: number, gap: number, pad: number, min: number) => Math.max(min, Math.ceil((n * gap) / TAU) - pad);

/** The orbit a body of radius `r` takes on once `n` tasks circle it, one more ring out each time the last fills. */
const orbit = (n: number, r: number, r0: number) => (n ? rings(n, r0, 9, 8).outer : r);

const CLEAR = 20, HOLD = 16;
/**
 * The last Board's routed paths and settled DAG bodies, each keyed on everything that places it. A stream delta rarely moves a state, so the
 * next Board reuses both searches instead of running them again on every task move.
 */
const last = { routes: { key: "", curves: [] as (Curve | null)[] }, bodies: { key: "", at: [] as Pt[] } };
/** The point on `g`'s rim facing `c`, where a path bending through `c` meets it. */
const rim = (g: Galaxy, c: Pt) => {
  const ex = c.x - g.x, ey = c.y - g.y, l = Math.hypot(ex, ey) || 1;
  return { x: g.x + (ex / l) * g.R, y: g.y + (ey / l) * g.R };
};
/**
 * A Board path between two states that passes no other state within CLEAR px. Where the path from `c0` would, its control point moves to a
 * spot on the sky where the path clears every other state; of those the one crossing the fewest paths already drawn and bending least wins,
 * so a path running straight through a state bends to the side that crosses fewer. `sky` bounds the control point. `held` is the bend the
 * path took last, which it keeps while that still clears.
 */
export function routed(a: Galaxy, b: Galaxy, c0: Pt, all: Galaxy[], drawn: Drawn, sky: Pt, held?: Pt): Curve {
  const others = all.filter((g) => g !== a && g !== b);
  const shape = (c: Pt): Curve => ({ p0: rim(a, c), c, p1: rim(b, c) });
  // both tests walk the same points sample() would give, without allocating them: every spot on the sky runs them
  const clear = ({ p0, c, p1 }: Curve, by = CLEAR) => {
    for (let i = 0; i <= 48; i++) {
      const t = i / 48, u = 1 - t, x = u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y = u * u * p0.y + 2 * u * t * c.y + t * t * p1.y;
      for (const g of others) if ((x - g.x) ** 2 + (y - g.y) ** 2 < (g.R + by) ** 2) return false;
    }
    return true;
  };
  const crossings = ({ p0, c, p1 }: Curve) => {
    let n = 0;
    for (let i = 0; i <= 30; i++) {
      const t = i / 30, u = 1 - t;
      if (drawn.near(u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, u * u * p0.y + 2 * u * t * c.y + t * t * p1.y)) n++;
    }
    return n;
  };
  const straight = shape(c0);
  // a bent path keeps its bend while it clears, and straightens only once the straight path clears by HOLD more, so a state growing and
  // shrinking across the line never flips it back and forth
  if (clear(straight, held ? CLEAR + HOLD : CLEAR)) return straight;
  if (held && clear(shape(held))) return shape(held);
  const spots: { c: Pt; bend: number }[] = [];
  for (let x = 10; x <= sky.x - 10; x += 40) for (let y = 10; y <= sky.y - 10; y += 40) spots.push({ c: { x, y }, bend: Math.hypot(x - c0.x, y - c0.y) / 200 });
  let best = straight, cost = Infinity;
  for (const { c, bend } of spots.sort((p, q) => p.bend - q.bend)) {
    if (bend >= cost) break;
    const e = shape(c);
    if (!clear(e)) continue;
    const crossed = crossings(e);
    if (bend + crossed < cost) [cost, best] = [bend + crossed, e];
  }
  return best;
}
/** The points of the paths drawn so far, bucketed in 10 px cells so a point checks only the nine cells round it for one within 10 px. */
export class Drawn {
  private cells = new Map<number, Pt[]>();
  private key = (x: number, y: number) => Math.floor(x / 10) * 65536 + Math.floor(y / 10);
  add(pts: Pt[]) {
    for (const d of pts) {
      const k = this.key(d.x, d.y), list = this.cells.get(k);
      if (list) list.push(d);
      else this.cells.set(k, [d]);
    }
  }
  near(x: number, y: number) {
    for (let i = -1; i <= 1; i++)
      for (let j = -1; j <= 1; j++) for (const d of this.cells.get(this.key(x + i * 10, y + j * 10)) ?? []) if (Math.hypot(d.x - x, d.y - y) < 10) return true;
    return false;
  }
}

/** Steps layered by dependency depth; a step caught in a dependency cycle counts from where the cycle was entered. */
function depths(steps: DagStep[]): Record<string, number> {
  const by = Object.fromEntries(steps.map((s) => [s.name, s])), depth: Record<string, number> = {};
  const dep = (n: string): number => {
    if (depth[n] === undefined) {
      depth[n] = 0;
      depth[n] = 1 + Math.max(-1, ...by[n].depends.filter((x) => by[x] && x !== n).map(dep));
    }
    return depth[n];
  };
  steps.forEach((s) => dep(s.name));
  return depth;
}
function columns(steps: DagStep[]) {
  const depth = depths(steps), cols: Record<number, DagStep[]> = {};
  steps.forEach((s) => (cols[depth[s.name]] ||= []).push(s));
  return { cols, L: Math.max(0, ...Object.keys(cols).map(Number)) + 1 };
}

/** A DAG drawn as its own step graph: steps layered by dependency depth, one link per dependency. */
export function glyph(d: Pick<Dag, "name" | "status" | "steps">): Glyph {
  const steps = d.steps || [], { cols, L } = columns(steps), SX = 28, SY = 18, pos: Record<string, GNode> = {}, nodes: GNode[] = [];
  for (const [l, list] of Object.entries(cols))
    list.forEach((s, i) => {
      const n = { name: s.name, status: s.status, x: (Number(l) - (L - 1) / 2) * SX, y: (i - (list.length - 1) / 2) * SY };
      pos[s.name] = n;
      nodes.push(n);
    });
  const links = steps.flatMap((s) => s.depends.filter((x) => pos[x]).map((x): [GNode, GNode] => [pos[x], pos[s.name]]));
  const w = (L - 1) * SX, h = (Math.max(1, ...Object.values(cols).map((c) => c.length)) - 1) * SY;
  return { nodes: nodes.length ? nodes : [{ name: d.name, status: d.status, x: 0, y: 0 }], links, w, h, br: Math.hypot(w, h) / 2 + 8 };
}

/** Orbit rings round a host: ring 0 at r0, each further ring ringGap out, bodies about `gap` apart; a ring is added when the last one fills. */
export function rings(n: number, r0: number, gap: number, ringGap: number) {
  const slots: { R: number; a0: number; w: number }[] = [], radii: number[] = [];
  let i = 0;
  for (let ring = 0; i < n; ring++) {
    const R = r0 + ring * ringGap, per = Math.max(6, Math.floor((TAU * R) / gap)), take = Math.min(per, n - i);
    radii.push(R);
    for (let j = 0; j < take; j++, i++) slots.push({ R, a0: (j / take) * TAU - Math.PI / 2 + ring * 0.37, w: (ring % 2 ? -1 : 1) * (TAU / 240) * (r0 / R) });
  }
  return { slots, radii, outer: radii.length ? radii[radii.length - 1] : r0 };
}

/** The gap between launch-only DAG dots beside a moon's name, in world units. */
export const OWNED = 12;
export const PAGE_SIZE = 12;
/** How many times its base width the Board's sky may grow before its states page their machines sooner than PAGE_SIZE, each by its own size. */
export const BOARD_GROW = 1.5;
/** The fewest machines a Board state's page drops to before the Board cuts its names, then grows its sky. */
export const MIN_PAGE = 4;

/** The lifecycle machines visible on one page of `size`; the primary machine is supplied separately and is never paged. */
export function paged(sid: string, list: string[], at = 0, size = PAGE_SIZE) {
  const pages = Math.ceil(list.length / size);
  if (pages <= 1) return { shown: list, hidden: [] as string[], pagers: [] as Pager[] };
  const page = ((at % pages) + pages) % pages, shown = list.slice(page * size, page * size + size), hidden = list.filter((n) => !shown.includes(n));
  // a hidden machine goes to the node whose turns reach its page sooner, forward on a tie
  const back = (i: number) => (page - Math.floor(i / size) + pages) % pages < (Math.floor(i / size) - page + pages) % pages;
  const pagers = ([-1, 1] as const).map((d): Pager => {
    const to = (page + d + pages) % pages + 1;
    return { sid, page, pages, d, hidden: list.filter((n, i) => hidden.includes(n) && back(i) === (d < 0)), title: d < 0 ? `‹ ${to}/${pages}` : `${to}/${pages} ›` };
  });
  return { shown, hidden, pagers };
}

/** The selected page after using one pager node. */
export const turnPage = (pager: Pager) => (pager.page + pager.d + pager.pages) % pager.pages;

/** How far either side of the ring's bottom its two pager nodes sit: clear of each other's orbit, and of the lowest machine rows. */
const pagerDx = (ring: number, orbit: number) => Math.max(0.3 * ring, orbit + 3);

const stub = (name: string): Dag => ({ name, status: "not_started", runId: "", startedAt: "", finishedAt: "", steps: [] });

/** Lay a level out for a W x H canvas. */
export function build(ctx: Ctx, l: Level): Scene {
  const scene = layoutLevel(ctx, l), pager = l.kind === "state" ? scene.planets.find((p) => p.pager)?.pager : undefined;
  // the view fits the frame, so a paged state is framed for every page: turning one never moves what is drawn on screen
  if (pager) {
    const boxes = Array.from({ length: pager.pages }, (_, i) => (i === pager.page ? scene : layoutLevel({ ...ctx, pages: { ...ctx.pages, [pager.sid]: i } }, l)).box!);
    scene.box = [Math.min(...boxes.map((b) => b[0])), Math.min(...boxes.map((b) => b[1])), Math.max(...boxes.map((b) => b[2])), Math.max(...boxes.map((b) => b[3]))];
  }
  return scene;
}

function layoutLevel(ctx: Ctx, l: Level): Scene {
  const { S, moves, W, H, T } = ctx, ease = ctx.ease ?? ((_key: string, v: number) => v), routes = ctx.routes ?? new Map<string, Pt>(), EVENTS = moves.events, board = S.board, SUBS = S.subs, dagBy = S.dagBy;
  const stateName = (id: string) => board.machine.states.find((s) => s.id === id)?.name || id;
  const scene: Scene = { w: 2460, h: 1340, galaxies: {}, bEdges: [], tasks: [], machineTasks: [], mStates: {}, mEdges: [], planets: [], moons: [], subStates: [], stars: {}, groups: [], sun: null, flow: null, hub: null, hops: [], entries: [], exits: [] };
  // Several DAGs on one path fold into one body. It runs while any of them runs, else shows the status of the one that finished last.
  const folds: Record<string, Dag & { fold: string[] }> = {};
  const foldOf = (ns: string[]) => {
    const ds = ns.map((n) => dagBy[n]), fin = ds.map((d) => d.finishedAt).filter(Boolean).sort().at(-1) ?? "";
    return { ...stub(`${ns.length} DAGs`), fold: ns, finishedAt: fin, status: ds.some((d) => d.status === "running") ? "running" : ds.find((d) => d.finishedAt === fin)?.status || "not_started" };
  };
  // a fold is a fanned stack of up to three steps, one per DAG, in each one's status colour
  const fan = (ns: string[]): Glyph => {
    const top = ns.slice(0, 3);
    return { nodes: top.map((n, i) => ({ name: n, status: dagBy[n]?.status || "not_started", x: (i - (top.length - 1) / 2) * 9, y: -(i - (top.length - 1) / 2) * 5 })), links: [], w: 18, h: 10, br: 18 };
  };
  // a DAG's instance prefix is drawn only where another instance runs a DAG by the same bare name
  const bare = (name: string) => name.slice(name.indexOf("/") + 1), bareCount = new Map<string, number>();
  for (const n of Object.keys(dagBy)) bareCount.set(bare(n), (bareCount.get(bare(n)) ?? 0) + 1);
  const labelOf = (name: string) => folds[name]?.name ?? (bareCount.get(bare(name)) === 1 ? bare(name) : name);
  const glyphOf = (name: string) => (folds[name] ? fan(folds[name].fold) : glyph(dagBy[name] || stub(name)));
  const star = (name: string, x: number, y: number): Star => {
    const d = folds[name] || dagBy[name] || stub(name), g = glyphOf(name);
    return { ...d, label: labelOf(name), x, y, glyph: g, br: g.br, group: S.dagGroup[name] || "", runnable: S.runnable.has(name) };
  };
  // lay DAG glyphs side by side, centred on cx, so wide step graphs never overlap their neighbours
  const row = (names: string[], cx: number, y: number, gap = 26) => {
    const gl = names.map((n) => glyph(dagBy[n] || stub(n))), total = gl.reduce((a, g) => a + g.w, 0) + gap * (names.length - 1);
    let x = cx - total / 2;
    return names.map((n, i) => {
      const s = star(n, x + gl[i].w / 2, y);
      x += gl[i].w + gap;
      scene.stars[n] = s;
      return s;
    });
  };
  const attach = (list: RawAgent[], host: Host, r0: number, gap: number, ringGap: number, big: boolean, speed = 1) => {
    const o = rings(list.length, r0, gap, ringGap);
    list.forEach((a, i) => scene.tasks.push({ ...a, host, ...o.slots[i], w: o.slots[i].w * speed, big, x: host.x, y: host.y, ang: 0, moving: false, arrive: null, gone: false, via: null, bev: [] }));
    host.rings = o.radii;
    return o.outer;
  };
  // A Board DAG writes a Board lane or is cued by a Board event. Every other DAG is free, a launcher included, and lives on the DAGs level.
  const boardTied = (n: string) => !!dagBy[n] && (Object.values(S.writers).some((ws) => ws.some((w) => w.actor === n)) || S.cues.some((c) => c.dag === n && !!board.machine.states.some((x) => x.id === c.state)));
  const freeDags = () => S.groups.flatMap((g) => g.dags.filter((n) => !boardTied(n)));

  // The DAGs level: every free DAG in one row of blocks, one per domain with its DAGs in name order under the domain's name, every block the
  // same number of rows. F is the world size of one screen pixel at fit, since names are drawn at screen size.
  function dock(w: number, F: number) {
    const size = (n: string) => {
      const g = glyph(dagBy[n] || stub(n));
      return { n, hw: Math.max(g.w / 2 + 12, (textW(labelOf(n), 11) * F) / 2 + 6), up: g.h / 2 + 10, dn: g.h / 2 + 16 * F + 12 };
    };
    type Item = ReturnType<typeof size>;
    const doms = S.groups.map((g) => ({ name: g.name, items: g.dags.filter((n) => !boardTied(n)).map(size) })).filter((d) => d.items.length);
    const GAP = 18, BGAP = 70, LBL = 24 * F;
    for (let R = 1; ; R++) {
      const blocks = doms.map((d) => {
        const total = d.items.reduce((a, q) => a + 2 * q.hw, 0) + GAP * (d.items.length - 1), rows: Item[][] = [[]];
        let acc = 0;
        for (const q of d.items) {
          if (rows.at(-1)!.length && rows.length < R && acc + GAP + q.hw > total / R) {
            rows.push([]);
            acc = 0;
          }
          acc += 2 * q.hw + (rows.at(-1)!.length ? GAP : 0);
          rows.at(-1)!.push(q);
        }
        const rw = rows.map((r) => r.reduce((a, q) => a + 2 * q.hw, 0) + GAP * (r.length - 1)), up = rows.map((r) => Math.max(...r.map((q) => q.up))), dn = rows.map((r) => Math.max(...r.map((q) => q.dn)));
        return { name: d.name, rows, rw, up, dn, w: Math.max(...rw), h: LBL + rows.reduce((a, _, i) => a + up[i] + dn[i], 0) + 8 * (rows.length - 1) };
      });
      const width = blocks.reduce((a, b) => a + b.w, 0) + BGAP * (blocks.length - 1);
      if (width > w - 120 && R < 8) continue;
      const items: { n: string; x: number; y: number }[] = [], labels: { name: string; x: number; y: number }[] = [];
      let x = w / 2 - width / 2;
      for (const b of blocks) {
        const mid = x + b.w / 2;
        let y = LBL;
        labels.push({ name: b.name, x: mid, y: LBL * 0.4 });
        b.rows.forEach((r, i) => {
          let rx = mid - b.rw[i] / 2;
          for (const q of r) {
            items.push({ n: q.n, x: rx + q.hw, y: y + b.up[i] });
            rx += 2 * q.hw + GAP;
          }
          y += b.up[i] + b.dn[i] + 8;
        });
        x += b.w + BGAP;
      }
      return { h: Math.max(0, ...blocks.map((b) => b.h)), width, items, labels, rows: R };
    }
  }

  function buildBoard() {
    // The Board's places come from its machine and its declared main line, scaled to the sky.
    const states = board.machine.states, transitions = board.machine.transitions;
    const BP = boardPlaces(states, transitions, board.machine.mainLine);
    const bx = Object.values(BP).map((q) => q[0]), by = Object.values(BP).map((q) => q[1]);
    const mx = (Math.min(...bx) + Math.max(...bx)) / 2, my = (Math.min(...by) + Math.max(...by)) / 2;
    const spanX = Math.max(...bx) - Math.min(...bx) || 1, spanY = Math.max(...by) - Math.min(...by) || 1;
    const byState: Record<string, RawAgent[]> = {};
    // a starting state orbits no task, as each is drawn where it went; a terminal state also orbits the day's arrivals there not already in it
    const initial = new Set(states.filter((s) => s.initial).map((s) => s.id)), final = new Set(states.filter((s) => s.final).map((s) => s.id));
    board.agents.forEach((a) => initial.has(a.state) || (byState[a.state] ||= []).push(a));
    for (const [sid, list] of Object.entries(S.today)) if (final.has(sid)) (byState[sid] ||= []).push(...list.filter((t) => !byState[sid]?.some((a) => a.id === t.id)));
    // A task orbits the deepest body this level draws that it is in: the sub-state its latest session holds (a CHILD entry, pr_opened while a PR
    // is open), else the moon of the machine it works when that is not its state's primary, else its state.
    const flowsOf = (sid: string) => (SUBS[sid] || []).filter((f) => S.flows[f]);
    const subStatesOf = (f: string) => S.flows[f].machine.states.filter((q) => S.child[f]?.[q.id]);
    const deepest = (a: RawAgent): { flow: string; state?: string } | null => {
      const q = S.latest[a.id], fs = flowsOf(a.state);
      if (a.today || !q || !fs.includes(q.flow)) return null;
      if (S.child[q.flow]?.[q.state]) return { flow: q.flow, state: q.state };
      return fs.indexOf(q.flow) > 0 ? { flow: q.flow } : null;
    };
    // A state's size follows its tasks: the planet, then the orbits the tasks that stay on it take, then the ring its machines sit on, grown
    // until every row of moons and sub-states fits.
    const radius = (st: (typeof states)[number]) => {
      const all = byState[st.id] || [], at = new Map(all.map((a) => [a, deepest(a)])), fs = flowsOf(st.id);
      const on = (f: string, state?: string) => all.filter((a) => at.get(a)?.flow === f && at.get(a)?.state === state);
      const k = st.id === "in_progress" ? 1.25 : 1, here = all.filter((a) => !at.get(a)), r = Math.min(GALAXY_MAX * k, oneRing(here.length, 11, 14, galaxyR(stateCount(S, st.id)) * k)), outer = here.length ? rings(here.length, r + 14, 11, 12).outer : r;
      const machine = (f: string) => {
        const ss = subStatesOf(f).map((q) => ({ ...q, name: q.name.replace(/^Pr /, "PR ") })), label = `${f}${ss.length ? ` › ${ss.map((q) => q.name).join(" · ")}` : ""}`;
        return { f, ss, label, slot: { moon: orbit(on(f).length, 9, 17), subs: ss.map((q) => orbit(on(f, q.id).length, 6, 14)), name: textW(clipped ? clip(label) : label, 10.5) * F } };
      };
      if (!fs.length) return { r, outer, R: outer + 10, rows: null, ms: [], pg: paged(st.id, []), here, on, at };
      const primary = machine(fs[0]), rest = fs.slice(1), pg = paged(st.id, rest, ctx.pages?.[st.id] ?? 0, sizes[st.id]);
      const pageCount = Math.max(1, pg.pagers[0]?.pages ?? 1), pageSets = Array.from({ length: pageCount }, (_, i) => [primary, ...paged(st.id, rest, i, sizes[st.id]).shown.map(machine)]), ms = [primary, ...pg.shown.map(machine)];
      const slots = Math.max(...pageSets.map((set) => set.length)), per: [number, number] = [Math.ceil(slots / 2), Math.floor(slots / 2)];
      // a pager node's orbit, at its busiest page, sizes the rows as a machine's does
      const pagerSets = pg.pagers.length ? Array.from({ length: pageCount }, (_, i) => paged(st.id, rest, i, sizes[st.id]).pagers).flat() : [];
      const pagerR = Math.max(0, ...pagerSets.map((pager) => orbit(all.filter((a) => pager.hidden.includes(at.get(a)?.flow ?? "")).length, 9, 17)));
      const bodies = [...pageSets.flatMap((set) => set.map((m) => Math.max(m.slot.moon, ...m.slot.subs))), ...(pagerR ? [pagerR] : [])], mR = Math.max(...bodies), rowH = Math.max(16 * F, ...bodies.map((body) => 2 * body + 6));
      const moonR = Math.max(outer + 10 + mR, (rowH * (per[0] + 1)) / 2);
      const offset = (i: number) => {
        const sd = i % 2, j = Math.floor(i / 2), dy = -moonR + ((j + 1) * 2 * moonR) / (per[sd] + 1);
        return { dx: (sd ? -1 : 1) * Math.sqrt(moonR ** 2 - dy ** 2), dy };
      };
      const reach: [number, number] = [moonR + mR, moonR + mR];
      for (const set of pageSets) set.forEach((m, i) => {
        const q = offset(i), sd = i % 2;
        reach[sd] = Math.max(reach[sd], Math.abs(q.dx) + m.slot.moon + m.slot.subs.reduce((e, body) => e + 8 + 2 * body, 0) + 10 + m.slot.name);
      });
      // the two pager nodes sit on the bottom of the ring, each named on its outer side
      const pagerAt = pagerDx(moonR, pagerR);
      if (pagerSets.length) for (const sd of [0, 1]) reach[sd] = Math.max(reach[sd], pagerAt + pagerR + 10 + Math.max(...pagerSets.map((pager) => textW(pager.title, 10.5))) * F);
      const rows = { moonR, R: moonR + 8 + mR, reach, pagerAt, at: ms.map((_, i) => offset(i)) };
      return { r, outer, R: rows.R, rows, ms, pg, here, on, at };
    };
    // The sky takes the canvas's shape, and the states fill it.
    const A = W / H, MINW = 1860, GAP = 40;
    let w = Math.max(MINW, Math.round(950 * A)), F = w / (0.94 * W);
    let hb = 0, clipped = false, Fcap = Infinity;
    const sizes: Record<string, number> = Object.fromEntries(states.map((st) => [st.id, PAGE_SIZE]));
    const w0 = w, hb0 = Math.round(w / A) - 40, sx = (w - 300) / spanX, sy = Math.min(1.25, (hb0 - 200) / spanY);
    // No state reaches its neighbour: where a state's tasks come within GAP of the next state beside it (or, when DAGs write the path between
    // the two, within the width of that path's DAG body, one DAG or its fold), that state and every state right of it move over until they
    // clear. The sky then grows to hold them, keeping the canvas's shape, and to keep the stacked states and their names on it. A wider sky
    // prints every name wider (F), so the sizes are measured again at each width until the sky holds them.
    const pathDags = (a: { id: string }, b: { id: string }) => [...new Set(transitions.filter((t) => (t.source === a.id && t.target === b.id) || (t.source === b.id && t.target === a.id))
      .flatMap((t) => [...(S.writers[t.event] || []).map((wr) => wr.actor), ...S.cues.filter((c) => c.event === t.event).map((c) => c.dag)]).filter(boardTied))];
    const gapOf = (a: { id: string }, b: { id: string }) => {
      const ds = pathDags(a, b);
      return ds.length ? GAP + (ds.length > 1 ? Math.max(60, textW(`${ds.length} DAGs`, 11) * F) : Math.max(glyph(dagBy[ds[0]]).w, textW(ds[0], 11) * F)) + 24 : GAP;
    };
    const SIDE = 20, free = freeDags(), doms = S.groups.filter((g) => g.dags.some((n) => free.includes(n))).length;
    const fit = (width: number) => {
      F = Math.min(width / (0.94 * W), Fcap);
      const sized = Object.fromEntries(states.map((st) => [st.id, radius(st)]));
      const ps = states.map((st) => ({ id: st.id, R: sized[st.id].R, x: w0 / 2 + (BP[st.id][0] - mx) * sx, y: hb0 / 2 + (BP[st.id][1] - my) * sy }));
      // States that share a slot stack outward from the axis, each GAP clear of the one before.
      const slots = new Map<string, typeof ps>();
      for (const p of ps) slots.set(`${BP[p.id][0]}/${BP[p.id][1] < AXIS_Y}`, [...(slots.get(`${BP[p.id][0]}/${BP[p.id][1] < AXIS_Y}`) || []), p]);
      for (const list of slots.values()) {
        const up = BP[list[0].id][1] < AXIS_Y ? -1 : 1;
        list.sort((a, b) => up * (a.y - b.y)).forEach((p, i) => {
          if (i) p.y = up < 0 ? Math.min(p.y, list[i - 1].y - list[i - 1].R - GAP - p.R) : Math.max(p.y, list[i - 1].y + list[i - 1].R + GAP + p.R);
        });
      }
      // the two sides of one column clear each other across the axis too, each moving half the overlap away from it
      for (const [key, up] of slots) {
        const down = slots.get(key.replace(/true$/, "false"));
        if (!key.endsWith("/true") || !down) continue;
        const lo = Math.max(...up.map((p) => p.y + p.R)), hi = Math.min(...down.map((p) => p.y - p.R)), over = lo + GAP - hi;
        if (over > 0) {
          for (const p of up) p.y -= over / 2;
          for (const p of down) p.y += over / 2;
        }
      }
      // the DAGs hangar holds the right end of the axis, opposite New, and keeps clear of the states beside it as a state does: its disc, its
      // ring of dots and the name and count below it
      const hangHW = Math.max(31, (Math.max(textW("DAGs", 12.5), textW(`${free.length} · ${doms} domains`, 10.5)) * F) / 2);
      const all = free.length ? [...ps, { id: "", R: 52 + 27 * F, x: Math.max(...ps.map((p) => p.x)), y: ps.find((p) => p.id === (board.machine.mainLine?.[0] ?? states[0].id))!.y }] : ps;
      const reach = (p: { id: string; R: number }, sd: 1 | -1) => (p.id ? (sized[p.id].rows?.reach[sd > 0 ? 0 : 1] ?? p.R) : hangHW);
      const shift = separate(all, gapOf, reach), grow = Math.max(0, ...shift.values());
      const over = Math.max(0, 56 * F - Math.min(...ps.map((p) => p.y - p.R)), Math.max(...ps.map((p) => p.y + p.R)) - (hb0 - 20));
      // the separation already widens the sky on the right; only the rest of the widening is centred
      const need = w0 + Math.ceil(Math.max(grow, 2 * over * A)), at = (p: (typeof ps)[number]) => p.x + shift.get(p)! + (need - w0 - grow) / 2;
      const left = Math.max(0, SIDE - Math.min(...all.map((p) => at(p) - reach(p, -1)))), right = Math.max(0, Math.max(...all.map((p) => at(p) + reach(p, 1))) + left - (need - SIDE));
      return { sized, ps: all, shift, grow, left, base: need, need: need + Math.ceil(left + right) };
    };
    // The width a sky needs rises about linearly with its width (names and rows are a fixed size on screen), so each pass solves the line
    // through the last two for where it meets the sky's own width; the widths are not sized apart, so a Board that cannot fit stops at the cap.
    const solve = (cap: number) => {
      w = w0;
      let fitted = fit(w), prev: { w: number; need: number } | null = null;
      for (let it = 0; it < 24 && fitted.need > w && w < cap; it++) {
        const slope = prev ? (fitted.need - prev.need) / (w - prev.w) : 0;
        prev = { w, need: fitted.need };
        w = slope > 0 && slope < 0.98 ? Math.max(fitted.need, Math.ceil((fitted.need - slope * w) / (1 - slope)) + 1) : fitted.need;
        fitted = fit(w);
      }
      return fitted;
    };
    // A Board that would grow past BOARD_GROW times its base pages its states' machines sooner, one state a step: the one whose page, one
    // machine shorter, takes the most width off the sky at that limit (the widest, when none does), until the sky holds or every page is down
    // to MIN_PAGE. Past that the names are cut to NAME_MAX, and then the sky grows: a Board this wide wants another level, not a wider row.
    const limit = BOARD_GROW * w0, shown = (id: string) => Math.min(sizes[id], Math.max(0, flowsOf(id).length - 1));
    let need = fit(limit).need;
    // when even every page at MIN_PAGE leaves the sky too wide, there is nothing to choose: page them all there and cut the names
    if (need > limit) {
      const full = { ...sizes };
      for (const st of states) sizes[st.id] = MIN_PAGE;
      if (fit(limit).need > limit) need = Infinity;
      else Object.assign(sizes, full);
    }
    while (need > limit && need < Infinity) {
      let best: { id: string; need: number; span: number } | null = null;
      for (const st of states) {
        if (shown(st.id) <= MIN_PAGE) continue;
        const was = sizes[st.id];
        sizes[st.id] = shown(st.id) - 1;
        const probe = fit(limit), span = probe.sized[st.id].rows?.reach.reduce((a, b) => a + b, 0) ?? 0;
        sizes[st.id] = was;
        if (!best || probe.need < best.need || (probe.need === best.need && span > best.span)) best = { id: st.id, need: probe.need, span };
      }
      if (!best) break;
      sizes[best.id] = shown(best.id) - 1;
      need = best.need;
    }
    // past the limit the names and rows stop growing with the sky, so a wider sky shows them smaller: the Board zooms out
    clipped = need > limit;
    Fcap = limit / (0.94 * W);
    const fitted = solve(8 * w0);
    const { sized, ps, shift, grow, left } = fitted;
    w = Math.max(w, fitted.need);
    // each state's place and the sky's width ease toward the layout's targets, so a state changing size moves its neighbours and the fit smoothly
    for (const p of ps) {
      p.x = ease(`${p.id || "hangar"}.x`, p.x + shift.get(p)! + (fitted.base - w0 - grow) / 2 + left + (w - fitted.need) / 2);
      p.y = ease(`${p.id || "hangar"}.y`, p.y + (Math.round(w / A) - 40 - hb0) / 2);
    }
    w = ease("sky.w", w);
    F = Math.min(w / (0.94 * W), Fcap);
    scene.w = w;
    scene.h = Math.round(w / A);
    scene.clipped = clipped;
    if (F < w / (0.94 * W)) scene.unit = F;
    hb = scene.h - 40;
    for (const st of states) {
      const p = ps.find((q) => q.id === st.id)!, { x, y } = p, { rows, ms, pg, here, on, at } = sized[st.id], r = ease(`${st.id}.r`, sized[st.id].r), R = ease(`${st.id}.R`, sized[st.id].R);
      const g: Galaxy = { id: st.id, name: st.name, x, y, r, n: stateCount(S, st.id), color: BOARD_COLOR[st.id] ?? "#94a3b8", final: st.final, today: daily(st) ? (S.today[st.id] ?? []).length : undefined, subs: SUBS[st.id] || [], R, moonR: 0, visR: 0, lab: { x, y }, reach: [R, R], loops: [] };
      const outer = here.length ? attach(here, g, r + 14, 11, 12, false) : r;
      g.moonR = ease(`${st.id}.moonR`, rows ? rows.moonR : outer + 16);
      if (rows) g.reach = rows.reach;
      g.visR = outer + 7; // a task hopping in orbits on the outer edge
      scene.galaxies[st.id] = g;
      // the machines are moons on the dashed ring, each with the tasks working it outside its sub-states; its sub-states run outward in its
      // row as a chain of small bodies, each with the tasks whose session holds it
      ms.forEach((m, i) => {
        const dx = ease(`${st.id}/${m.f}.dx`, rows!.at[i].dx), dy = ease(`${st.id}/${m.f}.dy`, rows!.at[i].dy), mx = x + dx, my = y + dy, sg = dx < 0 ? -1 : 1, tasks = on(m.f);
        const moon: Moon = { name: m.f, label: m.label, parent: g, x: mx, y: my, r: 9, R: 9, n: tasks.length, nStates: S.flows[m.f].machine.states.length, ext: 0, chain: [] };
        if (tasks.length) moon.R = attach(tasks, moon, 17, 9, 8, false);
        let c = moon.R, prev: Host = moon;
        for (const q of m.ss) {
          const ts = on(m.f, q.id), link = S.child[m.f][q.id], R = orbit(ts.length, 6, 14);
          c += 8;
          const b: SubState = { name: q.name, parent: g, machine: m.f, state: q.id, flow: link.flow, when: link.when, n: ts.length, x: mx + sg * (c + R), y: my, r: 6, R, color: "#e879f9", prev };
          if (ts.length) attach(ts, b, 14, 9, 8, false);
          c += 2 * R;
          prev = b;
          moon.chain.push(b);
          scene.subStates.push(b);
        }
        moon.ext = c - moon.R;
        scene.moons.push(moon);
      });
      for (const pager of pg.pagers) {
        const tasks = (byState[st.id] || []).filter((a) => pager.hidden.includes(at.get(a)?.flow ?? "")), dx = pager.d * rows!.pagerAt;
        const moon: Moon = { name: pager.title, label: pager.title, pager, parent: g, x: x + dx, y: y + Math.sqrt(g.moonR ** 2 - dx ** 2), r: 9, R: 9, n: tasks.length, nStates: 0, ext: 0, chain: [] };
        if (tasks.length) moon.R = attach(tasks, moon, 17, 9, 8, false);
        scene.moons.push(moon);
      }
    }
    // One path per ordered pair of states, carrying every event between them. A pair joined both ways bows to opposite sides and a one-way
    // path runs straight. A final state reached from several states (Archived) gathers its paths into one stream along its side of the Board. Then
    // any path that would pass another state bends away from it until it clears (routed).
    const gs = Object.values(scene.galaxies), pairs = merged(transitions, S.writers);
    const routeKey = JSON.stringify([w, hb, gs.map((g) => [g.id, g.x, g.y, g.R, g.final]), pairs.map((t) => [t.source, t.target]), [...routes]]);
    const reuse = last.routes.key === routeKey, curves: (Curve | null)[] = [];
    const drawn = new Drawn(), stays: BEdge[] = [];
    for (const tr of pairs) {
      const a = scene.galaxies[tr.source], b = scene.galaxies[tr.target];
      if (!a || !b || a === b) curves.push(null);
      if (!a || !b) continue;
      if (a === b) {
        a.loops.push(...tr.events);
        stays.push({ ...tr, loop: true });
        continue;
      }
      const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy), both = transitions.some((t) => t.source === tr.target && t.target === tr.source);
      const side = both ? (tr.source < tr.target ? 1 : -1) * 0.11 : 0;
      const gathers = b.final && new Set(transitions.filter((t) => t.target === b.id && t.source !== b.id).map((t) => t.source)).size > 1;
      const c0 = gathers ? { x: a.x + dx * 0.15, y: b.y } : { x: (a.x + b.x) / 2 - (dy / L) * L * side, y: (a.y + b.y) / 2 + (dx / L) * L * side };
      // a bend is kept in the frame of its two states (u along a→b, v across it), so a held route moves with them
      const k = `${tr.source}>${tr.target}`, h = routes.get(k), held = h && { x: a.x + h.x * dx - h.y * dy, y: a.y + h.x * dy + h.y * dx };
      const r = reuse ? last.routes.curves[curves.length] : routed(a, b, c0, gs, drawn, { x: w, y: hb }, held);
      curves.push(r);
      if (!reuse) drawn.add(sample(r!, 30));
      const ox = r!.c.x - a.x, oy = r!.c.y - a.y, u0 = (ox * dx + oy * dy) / L ** 2, v0 = (oy * dx - ox * dy) / L ** 2;
      if (Math.hypot(r!.c.x - c0.x, r!.c.y - c0.y) < 0.5) routes.delete(k);
      else routes.set(k, { x: u0, y: v0 });
      // the bend eases in that frame, so the path rides its states as they move, a re-route bends it over to its new shape instead of
      // snapping, and its ends stay on the rims facing the bend
      const u = ease(`${k}.u`, u0), v = ease(`${k}.v`, v0);
      const c = { x: a.x + u * dx - v * dy, y: a.y + u * dy + v * dx };
      scene.bEdges.push({ ...tr, p0: rim(a, c), c, p1: rim(b, c) });
    }
    last.routes = { key: routeKey, curves };
    const curve = (e: BEdge) => e as BEdge & Curve;
    // state names go above the state by default and drop below only where a path would run through the text
    const pts = scene.bEdges.flatMap((e) => sample(curve(e)));
    for (const g of Object.values(scene.galaxies)) {
      const f = F, hw = (Math.max(textW(g.name, 13), textW(`${countText(g.n, g.today)}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`, 11)) / 2) * f;
      const off = 14, top = g.y - g.R - off, bot = g.y + g.R + 6;
      const cands = [{ x0: g.x - hw, x1: g.x + hw, y0: top - 38 * f, y1: top, ly: top - 38 * f + 12 }, { x0: g.x - hw, x1: g.x + hw, y0: bot, y1: bot + 40 * f, ly: bot + 16 }];
      // the side that prints the name least over another state (one stacked in the same slot) or its moon rows, then the one fewer paths cross
      const on = (c: (typeof cands)[number]) => gs.reduce((a, o) => a + (o === g ? 0 : Math.max(0, Math.min(c.x1, o.x + o.reach[0]) - Math.max(c.x0, o.x - o.reach[1])) * Math.max(0, Math.min(c.y1, o.y + o.R) - Math.max(c.y0, o.y - o.R))), 0);
      const least = Math.min(...cands.map(on)), c = bestSide(cands.filter((x) => on(x) <= least + 1), pts);
      g.lab = { x: g.x, y: c.ly };
    }
    // DAGs: one glyph and one name each. A Board DAG (it writes a Board transition or is cued by a Board event) keeps one tether, drawn only
    // while it is hovered, to the middle of one path: the path carrying most of its criteria, a tie going to the path whose two states its
    // criteria touch most. A cue rides the path of the event it runs beside. Several DAGs that sit on one path (or beside one state) fold into
    // one body. A body settles beside its path so no glyph or name overlaps another, a state or a path. Every free DAG is on the DAGs level.
    interface Crit { edge?: BEdge; states: string[]; cue: boolean; text: string }
    const crit: Record<string, Crit[]> = {}, via = (e: BEdge) => `${stateName(e.source)} → ${stateName(e.target)}`;
    for (const e of [...scene.bEdges, ...stays])
      for (const wr of e.writers)
        if (dagBy[wr.actor]) (crit[wr.actor] ||= []).push(e.loop
          ? { states: [e.source], cue: false, text: `writes ${wr.event} (${stateName(e.source)})` }
          : { edge: e, states: [e.source, e.target], cue: false, text: `writes ${wr.event} (${via(e)})` });
    for (const c of S.cues) {
      if (!scene.galaxies[c.state] || !dagBy[c.dag]) continue;
      const e = scene.bEdges.find((x) => x.events.includes(c.event));
      (crit[c.dag] ||= []).push({ edge: e, states: e ? [e.source, e.target] : [c.state], cue: true, text: `runs on ${c.on}, beside ${c.event} (${e ? via(e) : stateName(c.state)})` });
    }
    const tethers: Record<string, Tether> = {};
    for (const [n, cs] of Object.entries(crit)) {
      const tally: Record<string, number> = {};
      for (const c of cs) for (const id of c.states) tally[id] = (tally[id] || 0) + 1;
      const score = (e: BEdge) => [cs.filter((c) => c.edge === e).length, tally[e.source] + tally[e.target]];
      const e = [...new Set(cs.flatMap((c) => (c.edge ? [c.edge] : [])))].sort((x, y) => { const [a1, a2] = score(x), [b1, b2] = score(y); return b1 - a1 || b2 - a2; })[0];
      const cue = cs.every((c) => c.cue), text = cs.map((c) => c.text), g = scene.galaxies[Object.keys(tally).sort((x, y) => tally[y] - tally[x])[0]];
      tethers[n] = e ? { ...bez(e.p0!, e.c!, e.p1!, 0.5), edge: e, cue, crit: text } : { x: g.x, y: g.y, g, cue, crit: text };
    }
    // DAGs on the same path (or beside the same state) fold into one body; its hover lists each of them with its criteria
    const byKey = new Map<string, string[]>();
    for (const n of Object.keys(tethers).sort()) {
      const t = tethers[n], k = t.edge ? `${t.edge.source}>${t.edge.target}` : t.g!.id!;
      byKey.set(k, [...(byKey.get(k) || []), n]);
    }
    for (const [k, ns] of byKey)
      if (ns.length > 1) {
        const key = `fold:${k}`;
        folds[key] = foldOf(ns);
        tethers[key] = { ...tethers[ns[0]], cue: ns.every((n) => tethers[n].cue), crit: ns.flatMap((n) => tethers[n].crit.map((t) => `${n}: ${t}`)) };
        for (const n of ns) delete tethers[n];
      }
    // a body on a path sits off the middle of it, on the side the path bows to (above a straight one); one with no path sits on an arc round
    // its state, centred on the side facing away from the middle of the Board
    const homes: Record<string, Pt> = {}, taken = new Map<BEdge, number>(), rank: Record<string, number> = {}, byG = new Map<Galaxy, string[]>();
    for (const n of Object.keys(tethers).sort()) {
      const { edge, g } = tethers[n];
      if (edge) {
        rank[n] = taken.get(edge) || 0;
        taken.set(edge, rank[n] + 1);
      } else byG.set(g as Galaxy, [...(byG.get(g as Galaxy) || []), n]);
    }
    for (const [n, t] of Object.entries(tethers)) {
      const e = t.edge;
      if (!e) continue;
      const gl = glyphOf(n), dx = e.p1!.x - e.p0!.x, dy = e.p1!.y - e.p0!.y, L = Math.hypot(dx, dy) || 1;
      let nx = -dy / L, ny = dx / L;
      const bow = (e.c!.x - (e.p0!.x + e.p1!.x) / 2) * nx + (e.c!.y - (e.p0!.y + e.p1!.y) / 2) * ny;
      if (bow < -1 || (Math.abs(bow) <= 1 && ny > 0)) [nx, ny] = [-nx, -ny];
      const r = 70 + Math.max(gl.w, gl.h) / 2 + 60 * rank[n];
      homes[n] = { x: t.x + nx * r, y: t.y + ny * r };
    }
    for (const [g, ns] of byG) {
      const ex = g.x - scene.w / 2, ey = g.y - hb / 2, l = Math.hypot(ex, ey), base = l > 40 ? Math.atan2(ey, ex) : Math.PI / 2, span = Math.min(Math.PI * 0.8, (ns.length - 1) * 0.6);
      ns.forEach((n, i) => {
        const a = base + (ns.length > 1 ? -span / 2 + (span * i) / (ns.length - 1) : 0), gl = glyphOf(n), r = g.R + 60 + Math.max(gl.w, gl.h) / 2;
        homes[n] = { x: g.x + Math.cos(a) * r, y: g.y + Math.sin(a) * r };
      });
    }
    const path = scene.bEdges.flatMap((e) => sample(curve(e), 40)), gal = Object.values(scene.galaxies);
    const hwOf = (n: string) => Math.max(glyphOf(n).w / 2 + 12, (textW(labelOf(n), 11) * F) / 2 + 6);
    const bodies = Object.keys(tethers).map((n) => {
      const g = glyphOf(n), home = homes[n];
      return { n, x: home.x, y: home.y, home, hw: hwOf(n), up: Math.max(g.h / 2 + 10, g.br + 6), dn: Math.max(g.h / 2, g.br) + 16 * F + 12, k: 0.03 };
    });
    const bodyKey = JSON.stringify([routeKey, scene.w, F, gal.map((g) => [g.name, g.lab.y, g.reach]), bodies.map((q) => [q.n, q.home.x, q.home.y, q.hw, q.up, q.dn])]);
    if (last.bodies.key === bodyKey) bodies.forEach((q, i) => Object.assign(q, last.bodies.at[i]));
    else settle();
    last.bodies = { key: bodyKey, at: bodies.map((q) => ({ x: q.x, y: q.y })) };
    function settle() {
    // the path in runs of 8 points with each run's x extent, so a body skips every run beside it and checks the rest in path order
    const px = Float64Array.from(path, (p) => p.x), py = Float64Array.from(path, (p) => p.y), runs = Math.ceil(px.length / 8);
    const lo = Float64Array.from({ length: runs }, (_, r) => Math.min(...px.subarray(r * 8, r * 8 + 8))), hi = Float64Array.from({ length: runs }, (_, r) => Math.max(...px.subarray(r * 8, r * 8 + 8)));
    // the pull toward home stops for the last tenth of the passes, so the separation settles exactly instead of balancing against it
    for (let it = 0; it < 400; it++)
      for (const q of bodies) {
        const k = it < 360 ? q.k : 0;
        q.x += (q.home.x - q.x) * k;
        q.y += (q.home.y - q.y) * k;
        for (const g of gal) {
          const nx = Math.max(q.x - q.hw, Math.min(g.x, q.x + q.hw)), ny = Math.max(q.y - q.up, Math.min(g.y, q.y + q.dn)), d = Math.hypot(nx - g.x, ny - g.y), R = g.R + 34 + (g.lab.y < g.y ? 0 : 20);
          if (d < R) {
            const dx = q.x - g.x, dy = q.y - g.y, L = Math.hypot(dx, dy) || 1;
            q.x += (dx / L) * Math.min(30, R - d);
            q.y += (dy / L) * Math.min(30, R - d);
          }
          // a state's whole column of moon names is kept clear, not only its rim
          if (g.reach[0] > g.R || g.reach[1] > g.R) {
            const x0 = g.x - g.reach[1] - 10, x1 = g.x + g.reach[0] + 10, y0 = g.y - g.R - 10, y1 = g.y + g.R + 10;
            if (q.x + q.hw > x0 && q.x - q.hw < x1 && q.y + q.dn > y0 && q.y - q.up < y1) q.y += (q.y < g.y ? -1 : 1) * Math.min(30, 1 + Math.min(q.y + q.dn - y0, y1 - (q.y - q.up)));
          }
          // the state's name and the count line under it
          const lw = (Math.max(textW(g.name, 13), textW(`${countText(g.n, g.today)}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`, 11)) * F) / 2 + 8, ly = g.lab.y;
          if (Math.abs(q.x - g.x) < q.hw + lw && ly > q.y - q.up - 30 && ly < q.y + q.dn + 30) q.y += (q.y < ly ? -1 : 1) * 6;
        }
        for (let ch = 0, x0 = q.x - q.hw - 6, x1 = q.x + q.hw + 6; ch < lo.length; ch++)
          if (hi[ch] > x0 && lo[ch] < x1)
            for (let i = ch * 8, end = Math.min(i + 8, px.length); i < end; i++)
              if (px[i] > x0 && px[i] < x1 && py[i] > q.y - q.up - 6 && py[i] < q.y + q.dn + 6) q.y += (q.y < py[i] ? -1 : 1) * 1.5;
        // neighbours last, so the other pulls cannot undo the separation and two DAGs that share a home end up apart
        for (const o of bodies)
          if (o !== q) {
            const ox = q.hw + o.hw + 14 - Math.abs(q.x - o.x), oy = (q.y < o.y ? q.dn + o.up : o.dn + q.up) + 10 - Math.abs(q.y - o.y);
            if (ox > 0 && oy > 0) {
              // two bodies with no room to part vertically (one rests on the dock's edge) part sideways
              const flat = Math.max(q.y, o.y) >= hb - Math.max(q.y > o.y ? q.dn : o.dn, 0) - 1;
              if (flat || ox / (q.hw + o.hw) < oy / 60) q.x += ((q.x < o.x ? -1 : 1) * Math.min(ox, 12)) / 2;
              else q.y += ((q.y < o.y ? -1 : 1) * Math.min(oy, 12)) / 2;
            }
          }
        q.x = Math.max(q.hw + 20, Math.min(scene.w - q.hw - 20, q.x));
        q.y = Math.max(q.up + 20, Math.min(hb - q.dn, q.y));
      }
    // bodies that still overlap (they were pressed against a state's ring) part vertically: the lower one moves down while the lane leaves room, else the upper one up
    for (let pass = 0; pass < 40; pass++)
      for (const q of bodies)
        for (const o of bodies) {
          const ox = q.hw + o.hw + 14 - Math.abs(q.x - o.x), oy = q.dn + o.up + 10 - (o.y - q.y);
          if (o === q || q.y > o.y || ox <= 0 || oy <= 0) continue;
          const down = Math.min(oy, Math.max(0, hb - o.dn - o.y));
          o.y += down;
          q.y -= oy - down;
        }
    // a body still on a state's name or its moon rows (caught between two names, the paths holding it there) takes the nearest height,
    // up or down, where it clears every state, name and other body
    const named = gal.map((g) => ({ g, lw: (Math.max(textW(g.name, 13), textW(`${countText(g.n, g.today)}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`, 11)) * F) / 2 + 8 }));
    const clearAt = (q: (typeof bodies)[number], y: number) => named.every(({ g, lw }) => {
      const wide = g.reach[0] > g.R || g.reach[1] > g.R, nx = Math.max(q.x - q.hw, Math.min(g.x, q.x + q.hw)), ny = Math.max(y - q.up, Math.min(g.y, y + q.dn));
      if (wide ? q.x + q.hw > g.x - g.reach[1] - 10 && q.x - q.hw < g.x + g.reach[0] + 10 && y + q.dn > g.y - g.R - 10 && y - q.up < g.y + g.R + 10 : Math.hypot(nx - g.x, ny - g.y) < g.R + 10) return false;
      return !(Math.abs(q.x - g.x) < q.hw + lw && y - q.up < g.lab.y + 21.5 * F + 6 && y + q.dn > g.lab.y - 6.5 * F - 6);
    }) && bodies.every((o) => o === q || q.hw + o.hw + 14 <= Math.abs(q.x - o.x) || (y < o.y ? q.dn + o.up : o.dn + q.up) + 10 <= Math.abs(y - o.y));
    for (const q of bodies)
      if (!clearAt(q, q.y))
        for (let d = 4; d < hb; d += 4) {
          const y = [q.y - d, q.y + d].find((v) => v - q.up >= 20 && v + q.dn <= hb && clearAt(q, v));
          if (y !== undefined) {
            q.y = y;
            break;
          }
        }
    }
    for (const q of bodies) scene.stars[q.n] = { ...star(q.n, q.x, q.y), tether: tethers[q.n] };
    scene.groups.push({ name: "", head: false, lx: 0, ly: 0, stars: bodies.map((q) => scene.stars[q.n]) });
    // every free DAG folds into one still body at the right end of the lifecycle axis, opposite New
    const hangar = ps.find((p) => !p.id);
    if (hangar) scene.hangar = { x: hangar.x, y: hangar.y, r: 22, names: free, doms };
  }

  // DAGs level: every free DAG in one row of domain blocks, centred on the canvas; a DAG opens its panel
  function buildDags() {
    const A = W / H;
    let w = 1860, F = w / (0.94 * W), D = dock(w, F);
    // the rows cap at eight, so many wide domains outgrow the scene: widen it until they fit
    for (let i = 0; i < 8 && D.width > w - 120; i++) {
      const nw = Math.ceil(D.width + 120), next = dock(nw, nw / (0.94 * W));
      if (next.width / nw >= D.width / w) break; // names scale with the scene, so past some size more width stops helping
      [w, D] = [nw, next];
    }
    w = Math.max(w, Math.round((D.h + 240) * A));
    F = w / (0.94 * W);
    D = dock(w, F);
    scene.w = w;
    scene.h = Math.round(w / A);
    const top = (scene.h - D.h) / 2;
    for (const q of D.items) scene.stars[q.n] = star(q.n, q.x, top + q.y);
    for (const grp of S.groups) {
      const lb = D.labels.find((x) => x.name === grp.name);
      if (lb) scene.groups.push({ name: grp.name, head: true, lx: lb.x, ly: top + lb.y, stars: grp.dags.map((n) => scene.stars[n]).filter(Boolean) });
    }
    // the blocks can lay out wider than the scene (the row count caps), so the fit frames what is drawn
    scene.box = boxOf([
      ...Object.values(scene.stars).flatMap((s) => {
        const hw = Math.max(s.glyph.w / 2, textW(s.label, 11) / 2) + 30;
        return [[s.x - hw, s.y - s.glyph.h / 2 - 30], [s.x + hw, s.y + s.glyph.h / 2 + 40]];
      }),
      ...scene.groups.map((g) => [g.lx, g.ly - 20]),
    ]);
  }

  // a band of related DAG stars across the top of a drilled-in level
  function dagBand(names: string[], label: string) {
    if (names.length) scene.groups.push({ name: label, lx: scene.w / 2, ly: 34, stars: row(names, scene.w / 2, 90, 150) });
  }

  // a lifecycle machine as a small solar system: its states on a ring (offsets from the planet centre), its transitions as chords
  function planet(name: string, cx: number, cy: number, R: number, primary: boolean): Planet {
    const flow = S.flows[name] ?? { name, machine: { states: [], transitions: [] }, agents: [] }, st = flow.machine.states, out: Record<string, MState> = {}, counts: Record<string, number> = {};
    flow.agents.forEach((a) => (counts[a.state] = (counts[a.state] || 0) + 1));
    st.forEach((s, i) => {
      const t = (i / st.length) * TAU - Math.PI / 2;
      out[s.id] = { id: s.id, name: s.name, final: s.final, initial: s.initial, flow: name, n: counts[s.id] || 0, loops: loopsOf(flow, s.id), mini: true,
        dx: Math.cos(t) * R, dy: Math.sin(t) * R, x: 0, y: 0, color: RAMP[Math.round((i / st.length) * (RAMP.length - 1))] };
    });
    const p: Planet = { name, R, primary, states: out, edges: flow.machine.transitions.map((t) => ({ ...t, flow: name, a: out[t.source], b: out[t.target] })), n: flow.agents.length, x: 0, y: 0 };
    place(p, cx, cy);
    return p;
  }

  // State level: the state's primary lifecycle machine sits at the centre with the machines its tasks open (skills) around it, joined by
  // paths as the Board joins its states; a state with no machines is a small sun. Each task orbits the machine it is working in, else the
  // primary. The Board transitions into and out of the state run as paths off the left and right edges.
  function buildState(sid: string) {
    const subs = (SUBS[sid] || []).filter((f) => S.flows[f]), bevOf = (id: string) => EVENTS.filter((e) => e.flow === "board" && e.task === id);
    // a task in the state or passing through it is drawn once, and on a terminal state a day's arrival there only when it is neither; a starting
    // state draws none
    const st = board.machine.states.find((s) => s.id === sid), here = st?.initial ? [] : board.agents.filter((a) => a.state === sid || bevOf(a.id).some((e) => e.from === sid || e.to === sid));
    const today = S.today[sid] ?? [], list = [...here, ...(st?.final ? today.filter((t) => !here.some((a) => a.id === t.id)) : [])];
    scene.h = subs.length ? 1300 : 820;
    scene.w = Math.max(subs.length ? 1800 : 1000, Math.round((scene.h * W) / H));
    scene.sid = sid;
    const cx0 = scene.w / 2, cy0 = scene.h / 2;
    if (!subs.length) {
      const n = stateCount(S, sid);
      const sun: Sun = { id: sid, name: stateName(sid), final: !!st?.final, today: st && daily(st) ? today.length : undefined, x: cx0, y: cy0, r: ease(`${sid}.r`, Math.min(GALAXY_MAX, oneRing(list.length, 16, 30, galaxyR(n)))), R: 0, n, color: BOARD_COLOR[sid] ?? "#94a3b8" };
      scene.sun = sun;
      scene.hub = sun;
      sun.R = attach(list, sun, sun.r + 30, 16, 16, true);
      sun.rim = sun.R + 8;
      scene.box = [sun.x - sun.R - 120, sun.y - sun.R - 120, sun.x + sun.R + 120, sun.y + sun.R + 120];
    } else {
      // the skill machines are moons: small named bodies the primary's machine opens, held still in rows once their orbits are known
      const allSkills = subs.slice(1), pg = paged(sid, allSkills, ctx.pages?.[sid] ?? 0), skills = pg.shown, hub = planet(subs[0], cx0, cy0, 104, true);
      const moons = skills.map((name) => Object.assign(planet(name, 0, 0, 9, false), { moon: true }));
      for (const pager of pg.pagers) moons.push({ name: pager.title, label: pager.title, pager, moon: true, primary: false, R: 9, x: 0, y: 0, states: {}, edges: [], chain: [], n: 0 });
      scene.hub = hub;
      // a skill machine's sub-states (its states that open a child machine) are small bodies in a chain beside its moon, each opening that machine
      const chains = moons.filter((p) => !p.pager).flatMap((p) => {
        const qs = S.flows[p.name].machine.states.filter((q) => S.child[p.name]?.[q.id]);
        p.chain = qs.map((q) => ({ name: `${p.name}>${q.id}`, title: q.name.replace(/^Pr /, "PR "), machine: p.name, state: q.id, flow: S.child[p.name][q.id].flow, when: S.child[p.name][q.id].when, subState: true,
          primary: false, R: 6, x: 0, y: 0, states: {}, edges: [], n: S.flows[p.name].agents.filter((a) => a.state === q.id).length }));
        if (p.chain.length) p.label = `${p.name} › ${p.chain.map((b) => b.title).join(" · ")}`;
        return p.chain;
      });
      scene.planets.push(hub, ...moons, ...chains);
      // a task orbits the deepest body drawn that it is in: the sub-state its latest event left it in, else the moon of the skill machine it works,
      // else the primary. It gets a place on each body it visits in the hour and hops between them as its session moves
      const rawHostAt = (id: string, t: number) => {
        const e = EVENTS.findLast((e) => e.task === id && e.at <= t && subs.includes(e.flow));
        return e && e.flow !== subs[0] && S.child[e.flow]?.[e.to] ? `${e.flow}>${e.to}` : e?.flow || subs[0];
      };
      // a task in a hidden machine orbits the pager node standing in for it
      const shown = (name: string) => pg.pagers.find((pager) => pager.hidden.includes(name.split(">")[0]))?.title ?? name;
      scene.hostAt = (id: string, t: number) => shown(rawHostAt(id, t));
      // on the primary, the trail names the primary's state (`in-progress#pr_opened`), so its moves inside the primary are hops too
      scene.hostTrail = (id: string) =>
        EVENTS.filter((e) => e.task === id && subs.includes(e.flow))
          .map((e) => ({ at: e.at, host: e.flow === subs[0] && hub.states[e.to] ? `${subs[0]}#${e.to}` : scene.hostAt!(id, e.at) }))
          .filter((r, i, all) => r.host !== all[i - 1]?.host);
      const rawVisits = list.map((a) => {
        const seen = new Set([rawHostAt(a.id, T - HOUR), rawHostAt(a.id, T)]);
        for (const e of EVENTS) if (e.task === a.id && e.at >= T - HOUR && subs.includes(e.flow)) seen.add(rawHostAt(a.id, e.at));
        return seen;
      });
      const byPlanet = new Map<Planet, RawAgent[]>(scene.planets.map((p) => [p, []]));
      list.forEach((a, i) => {
        const seen = new Set([...rawVisits[i]].map(shown));
        for (const name of seen) byPlanet.get(scene.planets.find((p) => p.name === name)!)!.push(a);
      });
      // the primary grows, its states with it, until its tasks circle it in one ring
      const grown = oneRing(byPlanet.get(hub)!.length, 17, 36, hub.R);
      for (const q of Object.values(hub.states)) [q.dx, q.dy] = [(q.dx! * grown) / hub.R, (q.dy! * grown) / hub.R];
      hub.R = grown;
      place(hub, cx0, cy0);
      for (const [p, ts] of byPlanet) {
        const small = p.moon || p.subState, [r0, gap, ringGap, pad] = small ? [p.R + 10, 9, 8, 4] : [p.R + 36, 17, 15, 14];
        p.outer = ts.length ? attach(ts, p, r0, gap, ringGap, true, 4) : p.R + pad;
        p.rim = p.outer + (small ? 3 : 8);
      }
      // the moons alternate right and left of the primary, then upper and lower, and stack in rows from the band beside the primary out to
      // four-fifths of the ring, so the Board paths keep the band and the DAGs keep the space above and below. A row is a line of type or the
      // moon's orbit, whichever is taller (type holds its screen size, so its height is estimated at the fit zoom); the ring grows until every
      // quarter's rows fit
      const shownMoons = moons.filter((p) => !p.pager), band = hub.rim! + 70, quads = [0, 1].flatMap((sd) => {
        const l = shownMoons.filter((_, i) => i % 2 === sd);
        return [l.filter((_, i) => i % 2 === 0), l.filter((_, i) => i % 2)];
      });
      // a row holds a moon and its sub-states, so it is as tall as the largest of their orbits
      const rowRim = (p: Planet) => 2 * Math.max(p.rim!, ...p.chain!.map((b) => b.rim!)) + 6;
      const count = (names: string[]) => rawVisits.filter((visit) => names.some((name) => visit.has(name))).length;
      const measuredOrbit = (n: number, r: number, r0: number, pad: number) => (n ? rings(n, r0, r, r - 1).outer : r) + pad;
      const measuredRim = (name: string) => {
        const qs = S.flows[name].machine.states.filter((q) => S.child[name]?.[q.id]);
        const own = measuredOrbit(count([name]), 9, 19, 4), subs = qs.map((q) => measuredOrbit(count([`${name}>${q.id}`]), 6, 16, 4));
        return 2 * Math.max(own, ...subs) + 6;
      };
      const pageQuads = Array.from({ length: pg.pagers[0]?.pages ?? 1 }, (_, i) => paged(sid, allSkills, i).shown.map(measuredRim)).flatMap((rims) =>
        [0, 1].flatMap((sd) => {
          const side = rims.filter((_, j) => j % 2 === sd);
          return [side.filter((_, j) => j % 2 === 0), side.filter((_, j) => j % 2)];
        }));
      let Rm = 440, lh = 20;
      for (let i = 0; i < 8; i++) {
        lh = 17 / Math.min((0.94 * W) / (2 * (Rm + 260)), (0.94 * H) / (2 * (Rm + 90)));
        Rm = Math.max(440, ...pageQuads.map((q) => (band + q.reduce((a, rim) => a + Math.max(lh, rim), 0)) / 0.8));
      }
      quads.forEach((q, qi) => {
        const sx = qi < 2 ? 1 : -1, sy = qi % 2 ? 1 : -1, rows = q.map((p) => Math.max(lh, rowRim(p))), gap = (0.8 * Rm - band - rows.reduce((a, b) => a + b, 0)) / Math.max(1, q.length);
        let y = band;
        q.forEach((p, j) => {
          y += gap / 2 + rows[j] / 2;
          place(p, cx0 + sx * Math.sqrt(Rm * Rm - y * y), cy0 + sy * y);
          y += rows[j] / 2 + gap / 2;
        });
      });
      scene.moonLH = lh;
      // the two pager nodes sit on the bottom of the ring, clear of each other at their busiest orbit across the pages
      const pagerOrbit = Math.max(0, ...Array.from({ length: pg.pagers[0]?.pages ?? 0 }, (_, i) => paged(sid, allSkills, i).pagers).flat().map((pager) =>
        measuredOrbit(rawVisits.filter((visit) => [...visit].some((name) => pager.hidden.includes(name.split(">")[0]))).length, 9, 19, 4)));
      for (const p of moons) if (p.pager) {
        const dx = p.pager.d * pagerDx(Rm, pagerOrbit + 3);
        place(p, cx0 + dx, cy0 + Math.sqrt(Rm * Rm - dx * dx));
      }
      for (const p of moons) {
        const sd = p.x < cx0 ? -1 : 1;
        let c = p.rim!, prev: Planet = p;
        for (const b of p.chain!) {
          c += 8;
          place(b, p.x + sd * (c + b.rim!), p.y);
          b.prev = prev;
          c += 2 * b.rim!;
          prev = b;
        }
        p.ext = c - p.rim!;
      }
      // the DAGs tied to this state hold still on rings round the primary: those that write a Board path into or out of it, launch a machine inside
      // it, or are cued by it. Hovering one draws its one tether. A DAG whose only tie is launching one skill machine orbits that machine instead
      const crit: Record<string, string[]> = {}, want: Record<string, number> = {}, launched: Record<string, Set<Planet>> = {}, F = lh / 17;
      for (const t of board.machine.transitions.filter((t) => t.source !== t.target && (t.source === sid || t.target === sid)))
        for (const w of S.writers[t.event] || []) if (dagBy[w.actor]) (crit[w.actor] ||= []).push(`writes ${t.event} (${stateName(t.source)} → ${stateName(t.target)})`);
      for (const l of S.launches) {
        const p = scene.planets.find((q) => q.name === l.flow && !q.subState);
        if (!p || !dagBy[l.dag]) continue;
        (crit[l.dag] ||= []).push(`launches ${l.flow}`);
        (launched[l.dag] ||= new Set()).add(p);
        if (p !== hub) want[l.dag] = Math.atan2(p.y - cy0, p.x - cx0);
      }
      for (const c of S.cues) if (c.state === sid && dagBy[c.dag]) (crit[c.dag] ||= []).push(`runs on ${c.on}, beside ${c.event}`);
      const tether = (n: string, to: Planet): Tether => ({ x: to.x, y: to.y, g: { x: to.x, y: to.y, R: to.rim! }, cue: crit[n].every((t) => t.startsWith("runs on")), crit: crit[n] });
      const owned = new Map<Planet, string[]>();
      for (const n of Object.keys(crit).sort()) {
        const ps = [...(launched[n] || [])];
        if (ps.length === 1 && ps[0] !== hub && crit[n].every((t) => t.startsWith("launches "))) owned.set(ps[0], [...(owned.get(ps[0]) || []), n]);
      }
      for (const [p, ns] of owned) {
        p.owned = ns.length;
        ns.forEach((n, i) => {
          scene.stars[n] = Object.assign(star(n, p.x + (p.x < cx0 ? -1 : 1) * (p.rim! + p.ext! + 16 + OWNED * i), p.y), { owned: p, br: 5, tether: tether(n, p) });
          delete crit[n];
        });
      }
      // DAGs with the same ties here fold into one body, as on the Board
      const byTies = new Map<string, string[]>();
      for (const n of Object.keys(crit).sort()) byTies.set(crit[n].join("|"), [...(byTies.get(crit[n].join("|")) || []), n]);
      for (const [k, ns] of byTies)
        if (ns.length > 1) {
          const key = `fold:${sid}:${k}`;
          folds[key] = foldOf(ns);
          crit[key] = ns.flatMap((n) => crit[n].map((t) => `${n}: ${t}`));
          if (ns[0] in want) want[key] = want[ns[0]];
          for (const n of ns) delete crit[n];
        }
      // angles round the primary that already carry something: each moon's path, the Board paths fanning in on the left and out on the right,
      // and the primary's own label below it. An entry with a radius blocks only that ring. A DAG takes the free angle nearest the machine it
      // launches (else straight above), and the next ring out when none is free
      const deg = Math.PI / 180, taken: [number, number, number?][] = [...moons.map((p): [number, number] => [Math.atan2(p.y - cy0, p.x - cx0), 8 * deg]), [Math.PI, 26 * deg], [0, 26 * deg], [Math.PI / 2, 28 * deg]];
      const norm = (a: number) => Math.atan2(Math.sin(a), Math.cos(a)), free = (a: number, w: number, r: number) => taken.every(([c, cw, tr]) => (tr && tr !== r) || Math.abs(norm(a - c)) > cw + w);
      const nearestFree = (from: number, w: number, r: number) => {
        for (let d = 0; d <= 180; d += 2) for (const sg of [1, -1]) if (free(from + sg * d * deg, w, r)) return from + sg * d * deg;
        return null;
      };
      const radii = Array.from({ length: 8 }, (_, i) => hub.rim! + 150 + 95 * i);
      const ring = Object.keys(crit).sort().map((n) => {
        let a: number | null = null, rD = radii[0];
        for (const r of radii) {
          const w = (Math.max(glyphOf(n).w / 2, (textW(labelOf(n), 11) * F) / 2) + 18) / r;
          a = nearestFree(want[n] ?? -Math.PI / 2, w, r);
          if (a !== null) {
            rD = r;
            taken.push([a, w, r]);
            break;
          }
        }
        a ??= want[n] ?? -Math.PI / 2;
        return (scene.stars[n] = Object.assign(star(n, cx0 + Math.cos(a) * rD, cy0 + Math.sin(a) * rD), { tether: tether(n, hub) }));
      });
      if (ring.length) scene.groups.push({ name: "", head: false, lx: cx0, ly: 0, stars: ring });
      // one path each way between the primary and each skill machine, rim to rim, bowed to opposite sides as the Board's paired transitions are
      for (const q of scene.planets.slice(1).filter((q) => !q.subState && !q.pager))
        for (const [a, b] of [[hub, q], [q, hub]]) {
          const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L, p0 = { x: a.x + ux * a.rim!, y: a.y + uy * a.rim! }, p1 = { x: b.x - ux * b.rim!, y: b.y - uy * b.rim! };
          const m = Math.hypot(p1.x - p0.x, p1.y - p0.y) * 0.14;
          scene.hops.push({ from: a.name, to: b.name, back: b === hub, p0, p1, c: { x: (p0.x + p1.x) / 2 - uy * m, y: (p0.y + p1.y) / 2 + ux * m } });
        }
      scene.box = boxOf([
        // every moon is named beside it; a pager node's orbit reaches below the ring
        ...moons.flatMap((p) => [[p.x + (p.x < cx0 ? -1 : 1) * (p.rim! + (p.ext ?? 0) + (p.owned ?? 0) * OWNED + 30 + (textW(p.label || p.name, 11.5) * lh) / 17), p.y], [p.x, p.y + p.rim!]]),
        ...ring.flatMap((s) => [[s.x - 90, s.y - 30], [s.x + 90, s.y + 50]]),
        [hub.x - hub.outer! - 110, hub.y - hub.outer! - 50], [hub.x + hub.outer! + 110, hub.y + hub.outer! + 90],
      ] as [number, number][]);
    }
    // the Board transitions into this state and out of it; edgePaths lays them out to the screen edges once the fit is known
    const tr = merged(board.machine.transitions.filter((t) => t.source !== t.target), S.writers);
    scene.entries = tr.filter((t) => t.target === sid);
    scene.exits = tr.filter((t) => t.source === sid);
    for (const k of scene.tasks) k.bev = bevOf(k.id);
  }

  function layered(name: string, x0: number, y0: number, w: number, h: number) {
    const flow = S.flows[name], st = flow.machine.states, layer: Record<string, number> = {}, q: string[] = [];
    st.filter((s) => s.initial).forEach((s) => { layer[s.id] = 0; q.push(s.id); });
    while (q.length) {
      const u = q.shift()!;
      for (const t of flow.machine.transitions) if (t.source === u && layer[t.target] === undefined) { layer[t.target] = layer[u] + 1; q.push(t.target); }
    }
    st.forEach((s) => { if (layer[s.id] === undefined) layer[s.id] = 0; });
    const max = Math.max(0, ...Object.values(layer)), cols: Record<number, typeof st> = {}, counts: Record<string, number> = {}, out: Record<string, MState> = {};
    st.forEach((s) => (cols[layer[s.id]] ||= []).push(s));
    flow.agents.forEach((a) => (counts[a.state] = (counts[a.state] || 0) + 1));
    for (const [l, list] of Object.entries(cols))
      list.forEach((s, i) => {
        out[s.id] = { id: s.id, name: s.name, final: s.final, initial: s.initial, flow: name, n: counts[s.id] || 0, loops: loopsOf(flow, s.id),
          x: x0 + (w * Number(l)) / Math.max(1, max), y: y0 + (h * (i + 1)) / (list.length + 1), color: RAMP[Math.round((Number(l) / Math.max(1, max)) * (RAMP.length - 1))] };
      });
    return out;
  }

  function buildMachine(name: string) {
    Object.assign(scene, { w: 1800, h: 1000, flow: name });
    const flow = S.flows[name];
    if (!flow) return;
    scene.mStates = layered(name, 180, 260, 1440, flow.machine.states.length > 8 ? 380 : 300);
    scene.mEdges = flow.machine.transitions.map((t) => ({ ...t, flow: name, a: scene.mStates[t.source], b: scene.mStates[t.target] }));
    // each state name takes the side (below, above, right, left) that crosses the fewest drawn paths, clear of its outermost ring of tasks
    const pts = scene.mEdges.flatMap((e) => (!e.a || !e.b || e.a === e.b ? [] : sample(curveOf(e.a, e.b), 34)));
    for (const s of Object.values(scene.mStates)) {
      const R = s.n ? taskSlot(stateR(s) + 7, s.n - 1).rr + 3 : stateR(s), w = textW(s.name, 12.5) / 2, up = R + 12;
      const c = bestSide([
        { x0: s.x - w, x1: s.x + w, y0: s.y + R + 4, y1: s.y + R + 26, lx: s.x, ly: s.y + R + 16 },
        { x0: s.x - w, x1: s.x + w, y0: s.y - up - 22, y1: s.y - up, lx: s.x, ly: s.y - up - 10 },
        { x0: s.x + R + 6, x1: s.x + R + 14 + 2 * w, y0: s.y - 11, y1: s.y + 11, lx: s.x + R + 10 + w, ly: s.y },
        { x0: s.x - R - 14 - 2 * w, x1: s.x - R - 6, y0: s.y - 11, y1: s.y + 11, lx: s.x - R - 10 - w, ly: s.y },
      ], pts);
      s.lab = { x: c.lx!, y: c.ly };
    }
    flow.agents.forEach((s) => scene.machineTasks.push({ ...s, flow: name }));
    for (const [sid, c] of Object.entries(S.child[name] || {})) {
      const a = scene.mStates[sid];
      if (!a || !S.flows[c.flow]) continue;
      const p = planet(c.flow, 0, 0, 50, false);
      p.anchor = a;
      p.when = c.when;
      place(p, a.x, a.y + 230);
      scene.planets.push(p);
    }
    // every DAG lives on the Board; one also shows here only when this machine is its one declared relationship (it launches only this
    // machine and writes no Board transition), so board-autopilot, which drives the Board, never appears inside a state
    const writesBoard = (d: string) => Object.values(S.writers).some((ws) => ws.some((w) => w.actor === d));
    dagBand([...new Set(S.launches.filter((x) => x.flow === name && dagBy[x.dag] && !writesBoard(x.dag) && S.launches.every((m) => m.dag !== x.dag || m.flow === name)).map((x) => x.dag))], "DAGs that launch this machine");
    scene.box = boxOf([
      ...Object.values(scene.mStates).flatMap((s) => { const w = textW(s.name, 12.5) / 2 + 10; return [[s.x - 50, s.y - 50], [s.x + 50, s.y + 50], [s.lab!.x - w, s.lab!.y - 20], [s.lab!.x + w, s.lab!.y + 20]]; }),
      ...scene.planets.flatMap((p) => [[p.x - p.R - 70, p.y - p.R - 40], [p.x + p.R + 70, p.y + p.R + 80]]),
      ...scene.groups.flatMap((g) => [[g.lx - 180, g.ly - 20], ...g.stars.flatMap((s) => [[s.x - s.br - 70, s.y - s.br - 20], [s.x + s.br + 70, s.y + s.br + 40]])]),
    ]);
  }

  // Fold level: the DAGs one Board fold stands for, as stars over the path they write. The path runs between its two states with each event the
  // DAGs write (or run beside) marked on it, and every DAG's ties to those events stay drawn, brighter on hover. A criterion's event and path
  // read from its text: "<dag>: writes EVENT (From → To)" or "<dag>: runs on X, beside EVENT (From → To)".
  const CRIT = /(writes|beside) ([A-Z_]+) \((.+?) → (.+?)\)/;
  function buildFold(l: Fold) {
    const w = 1800, h = Math.round(w / (W / H)), y = h * 0.62, f: FoldView = { events: [], ties: [] };
    Object.assign(scene, { w, h, fold: f });
    const end = (id: string, x: number): FoldEnd => ({ id, name: stateName(id), final: !!board.machine.states.find((s) => s.id === id)?.final, color: BOARD_COLOR[id] || "#94a3b8", x, y, r: 34 });
    const ties = (n: string) => l.crit.filter((t) => t.startsWith(`${n}: `)).map((t) => ({ text: t.slice(n.length + 2), m: CRIT.exec(t) }));
    if (l.path) {
      const [a, b] = l.path.map(stateName);
      f.a = end(l.path[0], 360);
      f.b = end(l.path[1], w - 360);
      f.p0 = { x: f.a.x + f.a.r + 8, y };
      f.p1 = { x: f.b.x - f.b.r - 8, y };
      const on = (m: RegExpExecArray | null) => m?.[3] === a && m?.[4] === b;
      const evs = [...new Set(l.dags.flatMap((n) => ties(n).filter((t) => on(t.m)).map((t) => t.m![2])))];
      f.events = evs.map((name, i) => ({ name, x: f.p0!.x + ((f.p1!.x - f.p0!.x) * (i + 1)) / (evs.length + 1), y }));
    }
    // the DAGs run in the order of the middle of the events each ties to along the path, so their ties do not cross
    const at = (n: string) => {
      const is = f.events.map((e, i) => (ties(n).some((t) => t.m?.[2] === e.name) ? i : -1)).filter((i) => i >= 0);
      return is.length ? is.reduce((p, q) => p + q) / is.length : Infinity;
    };
    const names = [...l.dags].sort((p, q) => at(p) - at(q) || p.localeCompare(q)), stars = row(names, w / 2, y - 280, 170);
    for (const st of stars) {
      const ts = ties(st.name);
      for (const e of f.events) {
        const mine = ts.filter((t) => t.m?.[2] === e.name);
        if (mine.length) f.ties.push({ dag: st.name, ev: e.name, x: e.x, y: e.y, cue: mine.every((t) => t.m![1] === "beside") });
      }
      st.tether = { x: st.x, y: st.y, cue: ts.length > 0 && ts.every((t) => t.m?.[1] === "beside"), crit: ts.map((t) => t.text) };
    }
    scene.groups.push({ name: "", head: false, lx: 0, ly: 0, stars });
    const xs = [...stars.map((q) => q.x), f.a?.x ?? w / 2, f.b?.x ?? w / 2];
    scene.box = [Math.min(...xs) - 140, y - 360, Math.max(...xs) + 140, y + 110];
  }

  if (l.kind === "board") buildBoard();
  else if (l.kind === "state") buildState(l.id);
  else if (l.kind === "dags") buildDags();
  else if (l.kind === "fold") buildFold(l);
  else buildMachine(l.flow);
  return scene;
}

function place(p: Planet, x: number, y: number) {
  p.x = x;
  p.y = y;
  for (const s of Object.values(p.states)) {
    s.x = x + s.dx!;
    s.y = y + s.dy!;
  }
}

/**
 * Lay the Board paths of a state level from the hub's rim to just past the left
 * and right screen edges at the fit view: entries fan in on the left, exits fan
 * out on the right, ranked the same at both ends so no two cross.
 */
export function edgePaths(scene: Scene, fit: { k: number; x: number }, W: number, stateName: (id: string) => string) {
  const hub = scene.hub!, left = -fit.x / fit.k - 60, right = (W - fit.x) / fit.k + 60, gap = 120, F = 1 / fit.k;
  for (const [list, side] of [[scene.entries, -1], [scene.exits, 1]] as const)
    list.forEach((l, i) => {
      const n = list.length, off = i - (n - 1) / 2, a = (side < 0 ? Math.PI : 0) + side * off * 0.2, rim = { x: hub.x + Math.cos(a) * hub.rim!, y: hub.y + Math.sin(a) * hub.rim! };
      const far = { x: side < 0 ? left : right, y: hub.y + off * gap }, c = { x: rim.x + side * 420, y: far.y };
      Object.assign(l, side < 0 ? { p0: far, c, p1: rim } : { p0: rim, c, p1: far });
      // the quiet name ("from Ready", "to Review") sits on the path just inside the screen edge
      const name = side < 0 ? `from ${stateName(l.source)}` : `to ${stateName(l.target)}`, inX = (textW(name, 10.5) / 2 + 24) * F;
      const pts = sample(l as BEdge & Curve, 80), q = side < 0 ? pts.find((p) => p.x >= left + 60 + inX) : pts.findLast((p) => p.x <= right - 60 - inX);
      l.lab = { name, x: (q || rim).x, y: (q || rim).y };
    });
}
