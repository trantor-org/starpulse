// Where everything on a level sits, ported from the approved round-13 mockup
// (the design mockup): the Board's states as galaxies with the
// DAGs as step-graph glyphs beside them, a state's lifecycle system as planets
// round its machine, one machine's states, the DAGs level, and a fold of DAGs over the Board path they write.
import { topOf, type Fold, type Level } from "./levels";
import { ledgerTop, sizes as ledgerSizes, type LedgerTop } from "./machineLedger";
import { nestsOf } from "./machineChain";
import { laneRows, type LaneNode, type LaneRow } from "./machineLanes";
import { laneContent } from "./machineScroll";
import { shownRows, type Paging } from "./machinePaging";
import { rankRows } from "./machineRows";
import { ledgerOf, type Ledger, type Tie } from "./ledger";
import type { Viewport } from "./ledgerScroll";
import { countText, daily, HOUR, hosted, stateCount, type Move, type Moves, type Sky } from "./sky";
import { pinsOf } from "./ledgerPins";
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
/** A Ledger template's tie to its event, drawn only while it is hovered. A cue is a looser tie than a write. `crit` is the hover's list of every criterion. */
export interface Tether extends Pt {
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
  /** How far the line bows from the chord, as a fraction of its length; the ledger bows a back edge more than a forward one. */
  bend?: number;
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
/** One DAG's cell in a merge row: its mini step graph centred at `gx` at scale `ms`, and the status line from `tx` in `room` world units. */
export interface GridCell {
  dag: string;
  gx: number;
  ms: number;
  tx: number;
  room: number;
}
/** The merge rows under a Ledger's cue bus: a viewport `view` tall from `top`, `rh` a row, the label gutter before the spine and the cross lane just past it. The rows scroll through it, drawn from one cell template. */
export interface LedgerGrid extends Viewport {
  /** The lane another repository's merges sit on. */
  lane: number;
  /** Where a row's time, task and title are written, and how wide that may run. */
  label: { x: number; w: number };
  /** A mini step's radius. */
  nr: number;
  /** Each template's cell, the same in every row. */
  cells: GridCell[];
  /** The unresolved band: the gap under its pins, the most pins it shows, and how many it shows now; they sit at the viewport's top and the rows scroll beneath. */
  gap: number;
  cap: number;
  pins: number;
  /** The 24-hour strip under the viewport: the spine to the right margin, `h` tall about `y`. */
  strip: { x0: number; x1: number; y: number; h: number };
}
/** A Ledger's frame: the junction every rail leaves from, the bus the cues hang from, and a caption cell for each DAG's template. */
export interface LedgerView extends Pick<Ledger, "event" | "rows"> {
  /** The event's mark on the path: over the DAG that writes it, else mid-path. */
  mark: Pt;
  J: Pt;
  /** The bus's height under the templates, and where their captions start. */
  bus: number;
  cap: number;
  cols: (Tie & { x0: number; x1: number; y0: number; y1: number })[];
  /** A merge Ledger's rows, when the server sent any. */
  grid?: LedgerGrid;
}
/** A fold's level: the DAGs one Board fold stands for. Over a Board path they are the Ledger of the event they are tied to, between the path's two states. */
export interface FoldView {
  a?: FoldEnd;
  b?: FoldEnd;
  p0?: Pt;
  p1?: Pt;
  ledger?: LedgerView;
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
  fold?: FoldView;
  /** A state level that opens a primary machine: that machine drawn across the top in screen pixels, over `mStates`, `mEdges` and `machineTasks`. */
  top?: MachineTop;
}
/** The machine across a level's top: where each state and name sits, how tall it is, and the states some other machine is entered from. */
export interface MachineTop extends LedgerTop {
  flow: string;
  entered: string[];
  /** The machines entered from this one, newest activity first: each row's height and states, the lane's top and bottom in canvas pixels. */
  rows: RowView[];
  laneTop: number;
  laneBottom: number;
  /** Every machine entered from this one, those below the loaded page among them; `more` of them are not loaded yet. */
  total: number;
  /** Every machine entered from this one, in the order the rows run (those not loaded last). */
  ranked: string[];
  more: number;
  /** The pinned task the rows are narrowed to, when one is. */
  task?: string;
  /** The height of the footer that closes the loaded rows while older machines remain, and how tall rows and footer are together and how far they scroll. */
  foot: number;
  content: number;
  max: number;
}
/** One machine entered from the top, placed in the lane; `y` is down from the lane's top. */
export interface RowView extends Omit<LaneRow, "nodes"> {
  nodes: (LaneNode & { color: string })[];
  /** The machine's first state, where a tie or a DAG launch arrives. */
  init: string;
}
export interface Ctx {
  S: Sky;
  moves: Moves;
  /** The canvas size the level is laid out for. */
  W: number;
  H: number;
  /** The page clock, in seconds. */
  T: number;
  /** The Board state a machine level opens under; a machine several states open shows only that state's tasks. */
  host?: string;
  /** The selected zero-based machine page for each Board state. */
  pages?: Record<string, number>;
  /** The value a layout value `v` named `key` shows: the renderer eases it from the value it showed when a snapshot changes it. The layout
   *  computes its targets from the true sizes, so an eased value never moves another's target. */
  ease?: (key: string, v: number) => number;
  /** Each bent Board path's last bend (`x` along source → target, `y` across it, as fractions of its length), kept by the renderer from one
   *  Board to the next so a path keeps its route while that still clears (routed). */
  routes?: Map<string, Pt>;
  /** The page's text size, as a percentage: a Ledger's captions are type, so its columns widen with it. */
  scale?: number;
  /** A string's width on the canvas at a font size and weight, in the type the names are drawn in; the layout estimates it when absent. */
  measure?: (s: string, px: number, weight?: number) => number;
  /** The boxes the page draws over the canvas (its crumb and clock), and how far down the crumb ends: a state level's top keeps its names and header clear of them. */
  chrome?: { avoid: { x0: number; y0: number; x1: number; y1: number }[]; inset: number };
  /** The order the page is holding its machine ledger rows in while the pointer is over them: the rows keep it, and a new machine goes last. */
  held?: string[];
  /** How much of the top's machine ledger is loaded: the rows below its boundary are left for the footer to bring in. */
  paging?: Paging | null;
  /** A pinned task and the machines it has a session in: the ledger shows only those rows, every one the snapshot holds, with no footer. */
  only?: { task: string; machines: readonly string[] };
}

export const bez = (p0: Pt, c: Pt, p1: Pt, t: number): Pt => {
  const u = 1 - t;
  return { x: u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y: u * u * p0.y + 2 * u * t * c.y + t * t * p1.y };
};
export const curveOf = (a: Pt, b: Pt, bend = 0.15): Curve => {
  const dx = b.x - a.x, dy = b.y - a.y;
  return { p0: a, p1: b, c: { x: (a.x + b.x) / 2 - dy * bend, y: (a.y + b.y) / 2 + dx * bend } };
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

/** The events a machine takes from one of its states back to the same state. */
const loopsOf = (flow: { machine: { transitions: Transition[] } }, id: string) => flow.machine.transitions.filter((t) => t.source === id && t.target === id).map((t) => t.event);
/** A Board state's radius: GALAXY_MIN with no tasks, growing with the square root of its count to GALAXY_MAX, which it reaches near 450 tasks. */
export const GALAXY_MIN = 34, GALAXY_MAX = 140;
const galaxyR = (n: number) => Math.min(GALAXY_MAX, GALAXY_MIN + 5 * Math.sqrt(n));
/**
 * A Board state's sun from its `share` of the week's moves, `busiest` being the largest share: its area is proportional to the share, the
 * busiest state's reaching GALAXY_MAX, and a quiet state keeps GALAXY_MIN so it stays visible.
 */
export const sunR = (share: number, busiest: number) => Math.max(GALAXY_MIN, GALAXY_MAX * Math.sqrt(busiest ? share / busiest : 0));
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
 * The last Board's routed paths, keyed on everything that places them. A stream delta rarely moves a state, so the next Board reuses the
 * search instead of running it again on every task move.
 */
const last = { routes: { key: "", curves: [] as (Curve | null)[] } };
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

/** A step graph drawn `k` times its size: the same steps and links, further apart. */
function scaled(g: Glyph, k: number): Glyph {
  const nodes = g.nodes.map((n) => ({ ...n, x: n.x * k, y: n.y * k })), at = new Map(g.nodes.map((n, i) => [n, nodes[i]]));
  return { nodes, links: g.links.map(([p, q]) => [at.get(p)!, at.get(q)!]), w: g.w * k, h: g.h * k, br: Math.hypot(g.w * k, g.h * k) / 2 + 8 };
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
  // a state the server sized (`Sky.suns`) takes its sun from its share of the week's moves, which live tasks never change; one it did not takes it from its count
  const sunSized = (id: string) => id in S.suns, busiest = Math.max(0, ...Object.values(S.suns));
  const stateName = (id: string) => board.machine.states.find((s) => s.id === id)?.name || id;
  const scene: Scene = { w: 2460, h: 1340, galaxies: {}, bEdges: [], tasks: [], machineTasks: [], mStates: {}, mEdges: [], planets: [], moons: [], subStates: [], stars: {}, groups: [], sun: null, flow: null, hub: null, hops: [], entries: [], exits: [] };
  // a DAG's instance prefix is drawn only where another instance runs a DAG by the same bare name
  const bare = (name: string) => name.slice(name.indexOf("/") + 1), bareCount = new Map<string, number>();
  for (const n of Object.keys(dagBy)) bareCount.set(bare(n), (bareCount.get(bare(n)) ?? 0) + 1);
  const labelOf = (name: string) => (bareCount.get(bare(name)) === 1 ? bare(name) : name);
  const star = (name: string, x: number, y: number): Star => {
    const d = dagBy[name] || stub(name), g = glyph(d);
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
      const k = st.id === "in_progress" ? 1.25 : 1, here = all.filter((a) => !at.get(a)), r = sunSized(st.id) ? sunR(S.suns[st.id], busiest) * k : Math.min(GALAXY_MAX * k, oneRing(here.length, 11, 14, galaxyR(stateCount(S, st.id)) * k)), outer = here.length ? rings(here.length, r + 14, 11, 12).outer : r;
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
    let clipped = false, Fcap = Infinity;
    const sizes: Record<string, number> = Object.fromEntries(states.map((st) => [st.id, PAGE_SIZE]));
    const w0 = w, hb0 = Math.round(w / A) - 40, sx = (w - 300) / spanX, sy = Math.min(1.25, (hb0 - 200) / spanY);
    // No state reaches its neighbour: where a state's tasks come within GAP of the next state beside it, that state and every state right of it
    // move over until they clear. The sky then grows to hold them, keeping the canvas's shape, and to keep the stacked states and their names on
    // it. A wider sky prints every name wider (F), so the sizes are measured again at each width until the sky holds them.
    const SIDE = 20;
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
      const reach = (p: { id: string; R: number }, sd: 1 | -1) => sized[p.id].rows?.reach[sd > 0 ? 0 : 1] ?? p.R;
      const shift = separate(ps, () => GAP, reach), grow = Math.max(0, ...shift.values());
      const over = Math.max(0, 56 * F - Math.min(...ps.map((p) => p.y - p.R)), Math.max(...ps.map((p) => p.y + p.R)) - (hb0 - 20));
      // the separation already widens the sky on the right; only the rest of the widening is centred
      const need = w0 + Math.ceil(Math.max(grow, 2 * over * A)), at = (p: (typeof ps)[number]) => p.x + shift.get(p)! + (need - w0 - grow) / 2;
      const left = Math.max(0, SIDE - Math.min(...ps.map((p) => at(p) - reach(p, -1)))), right = Math.max(0, Math.max(...ps.map((p) => at(p) + reach(p, 1))) + left - (need - SIDE));
      return { sized, ps, shift, grow, left, base: need, need: need + Math.ceil(left + right) };
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
      p.x = ease(`${p.id}.x`, p.x + shift.get(p)! + (fitted.base - w0 - grow) / 2 + left + (w - fitted.need) / 2);
      p.y = ease(`${p.id}.y`, p.y + (Math.round(w / A) - 40 - hb0) / 2);
    }
    w = ease("sky.w", w);
    F = Math.min(w / (0.94 * W), Fcap);
    scene.w = w;
    scene.h = Math.round(w / A);
    scene.clipped = clipped;
    if (F < w / (0.94 * W)) scene.unit = F;
    const hb = scene.h - 40;
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
    const drawn = new Drawn();
    for (const tr of pairs) {
      const a = scene.galaxies[tr.source], b = scene.galaxies[tr.target];
      if (!a || !b || a === b) curves.push(null);
      if (!a || !b) continue;
      if (a === b) {
        a.loops.push(...tr.events);
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
  }

  // a lifecycle machine as a small solar system: its states on a ring (offsets from the planet centre), its transitions as chords
  function planet(name: string, cx: number, cy: number, R: number, primary: boolean, host?: string): Planet {
    const flow = S.flows[name] ?? { name, machine: { states: [], transitions: [] }, agents: [] }, st = flow.machine.states, out: Record<string, MState> = {}, counts: Record<string, number> = {}, agents = hosted(S, name, host);
    agents.forEach((a) => (counts[a.state] = (counts[a.state] || 0) + 1));
    st.forEach((s, i) => {
      const t = (i / st.length) * TAU - Math.PI / 2;
      out[s.id] = { id: s.id, name: s.name, final: s.final, initial: s.initial, flow: name, n: counts[s.id] || 0, loops: loopsOf(flow, s.id), mini: true,
        dx: Math.cos(t) * R, dy: Math.sin(t) * R, x: 0, y: 0, color: RAMP[Math.round((i / st.length) * (RAMP.length - 1))] };
    });
    const p: Planet = { name, R, primary, states: out, edges: flow.machine.transitions.map((t) => ({ ...t, flow: name, a: out[t.source], b: out[t.target] })), n: agents.length, x: 0, y: 0 };
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
      const sun: Sun = { id: sid, name: stateName(sid), final: !!st?.final, today: st && daily(st) ? today.length : undefined, x: cx0, y: cy0, r: ease(`${sid}.r`, sunSized(sid) ? sunR(S.suns[sid], busiest) : Math.min(GALAXY_MAX, oneRing(list.length, 16, 30, galaxyR(n)))), R: 0, n, color: BOARD_COLOR[sid] ?? "#94a3b8" };
      scene.sun = sun;
      scene.hub = sun;
      sun.R = attach(list, sun, sun.r + 30, 16, 16, true);
      sun.rim = sun.R + 8;
      scene.box = [sun.x - sun.R - 120, sun.y - sun.R - 120, sun.x + sun.R + 120, sun.y + sun.R + 120];
    } else {
      // the skill machines are moons: small named bodies the primary's machine opens, held still in rows once their orbits are known
      const allSkills = subs.slice(1), pg = paged(sid, allSkills, ctx.pages?.[sid] ?? 0), skills = pg.shown, hub = planet(subs[0], cx0, cy0, 104, true, sid);
      const moons = skills.map((name) => Object.assign(planet(name, 0, 0, 9, false, sid), { moon: true }));
      for (const pager of pg.pagers) moons.push({ name: pager.title, label: pager.title, pager, moon: true, primary: false, R: 9, x: 0, y: 0, states: {}, edges: [], chain: [], n: 0 });
      scene.hub = hub;
      // a skill machine's sub-states (its states that open a child machine) are small bodies in a chain beside its moon, each opening that machine
      const chains = moons.filter((p) => !p.pager).flatMap((p) => {
        const qs = S.flows[p.name].machine.states.filter((q) => S.child[p.name]?.[q.id]);
        p.chain = qs.map((q) => ({ name: `${p.name}>${q.id}`, title: q.name.replace(/^Pr /, "PR "), machine: p.name, state: q.id, flow: S.child[p.name][q.id].flow, when: S.child[p.name][q.id].when, subState: true,
          primary: false, R: 6, x: 0, y: 0, states: {}, edges: [], n: hosted(S, p.name, sid).filter((a) => a.state === q.id).length }));
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
      // one path each way between the primary and each skill machine, rim to rim, bowed to opposite sides as the Board's paired transitions are
      for (const q of scene.planets.slice(1).filter((q) => !q.subState && !q.pager))
        for (const [a, b] of [[hub, q], [q, hub]]) {
          const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L, p0 = { x: a.x + ux * a.rim!, y: a.y + uy * a.rim! }, p1 = { x: b.x - ux * b.rim!, y: b.y - uy * b.rim! };
          const m = Math.hypot(p1.x - p0.x, p1.y - p0.y) * 0.14;
          scene.hops.push({ from: a.name, to: b.name, back: b === hub, p0, p1, c: { x: (p0.x + p1.x) / 2 - uy * m, y: (p0.y + p1.y) / 2 + ux * m } });
        }
      scene.box = boxOf([
        // every moon is named beside it; a pager node's orbit reaches below the ring
        ...moons.flatMap((p) => [[p.x + (p.x < cx0 ? -1 : 1) * (p.rim! + (p.ext ?? 0) + 30 + (textW(p.label || p.name, 11.5) * lh) / 17), p.y], [p.x, p.y + p.rim!]]),
        [hub.x - hub.outer! - 110, hub.y - hub.outer! - 50], [hub.x + hub.outer! + 110, hub.y + hub.outer! + 90],
      ] as [number, number][]);
    }
    // the Board transitions into this state and out of it; edgePaths lays them out to the screen edges once the fit is known
    const tr = merged(board.machine.transitions.filter((t) => t.source !== t.target), S.writers);
    scene.entries = tr.filter((t) => t.target === sid);
    scene.exits = tr.filter((t) => t.source === sid);
    for (const k of scene.tasks) k.bev = bevOf(k.id);
  }

  // The machine across the top of a state level that opens a primary machine (machineLedger.ts): its states, flow lines and tasks in screen
  // pixels, so the hover and panels the machine level has work on it unchanged.
  const tasksOf = (f: { agents: { state: string }[] }) => {
    const n: Record<string, number> = {};
    for (const a of f.agents) n[a.state] = (n[a.state] ?? 0) + 1;
    return n;
  };
  function buildTop(name: string, like?: string) {
    const flow = S.flows[name];
    if (!flow) return;
    const agents = hosted(S, name, ctx.host), tasks = tasksOf({ agents });
    const frame = { W, H, scale: ctx.scale ?? 100, measure: ctx.measure ?? ((t: string, px: number) => t.length * (px * 0.56 + 0.6)), ...ctx.chrome };
    // a machine opened from a row stands as tall as the machine it was opened from
    const model = like && S.flows[like], height = model ? ledgerTop({ states: model.machine.states, transitions: model.machine.transitions, tasks: tasksOf(model), entered: [] }, frame).hdrB : undefined;
    const entered = [...new Set([...Object.keys(S.child[name] ?? {}), ...Object.values(S.flows).flatMap((f) => (f.ties?.[0]?.machine === name && f.ties[0].state ? [f.ties[0].state] : []))])];
    const top = ledgerTop({ states: flow.machine.states, transitions: flow.machine.transitions, tasks, entered }, { ...frame, height });
    const { fs } = ledgerSizes(ctx.scale ?? 100), laneTop = top.hdrB + 6, laneBottom = H - 50 * fs;
    const only = ctx.only, ranked = rankRows(S.flows, name, ctx.held).filter((m) => !only || only.machines.includes(m));
    const order = shownRows(ranked, (m) => S.flows[m].last ?? 0, !only && ctx.paging?.top === name ? ctx.paging : null), machines = order.map((m) => ({ name: m, states: S.flows[m].machine.states, transitions: S.flows[m].machine.transitions, tasks: tasksOf(S.flows[m]), nested: nestsOf(S.flows, m) }));
    const lane = laneRows(machines, { x0: top.x0, x1: top.x1 }, { scale: ctx.scale ?? 100, laneH: laneBottom - laneTop, total: ranked.length, measure: frame.measure });
    const rows = lane.rows.map((r): RowView => {
      const st = S.flows[r.name].machine.states;
      return { ...r, init: (st.find((x) => x.initial) ?? st[0]).id, nodes: r.nodes.map((n) => ({ ...n, color: RAMP[Math.round(n.u * (RAMP.length - 1))] })) };
    });
    const more = ranked.length - rows.length, foot = more ? 34 * fs : 0;
    scene.top = { ...top, flow: name, entered, rows, laneTop, laneBottom, total: ranked.length, ranked, more, foot, task: only?.task, ...laneContent(rows, foot, { h: laneBottom - laneTop, fs }) };
    for (const n of top.nodes) scene.mStates[n.id] = { id: n.id, name: n.name, final: n.final, initial: n.initial, flow: name, n: n.n, x: n.x, y: n.y, loops: loopsOf(flow, n.id), color: RAMP[Math.round(n.u * (RAMP.length - 1))] };
    scene.mEdges = flow.machine.transitions.map((t) => {
      const a = scene.mStates[t.source], b = scene.mStates[t.target];
      return { ...t, flow: name, a, b, bend: a && b && b.x < a.x - 1 ? 0.28 : 0.08 };
    });
    agents.forEach((a) => scene.machineTasks.push({ ...a, flow: name }));
  }

  // Fold level. A fold over a Board path is that path's Ledger (ledger.ts): the DAGs tied to the event as templates in one row, the DAG that
  // writes it first, under the path with the event marked on it, a junction every rail leaves from and a bus the cues hang from. Type is a
  // fixed size on screen, so what its captions need is laid out in world units through F, a screen pixel's world size at fit. A fold with no
  // path, or none an event is tied to, is its DAGs in a row.
  function buildFold(l: Fold) {
    const led = ledgerOf({ flows: [board], cues: S.cues }, l), f: FoldView = {};
    let w = 1800, h = Math.round(w / (W / H));
    const crit = (n: string) => l.crit.filter((t) => t.startsWith(`${n}: `)).map((t) => t.slice(n.length + 2));
    if (!led) {
      const stars = row(l.dags, w / 2, h / 2, 170);
      for (const st of stars) st.tether = { x: st.x, y: st.y, cue: crit(st.name).every((t) => t.includes("beside")), crit: crit(st.name) };
      scene.groups.push({ name: "", head: false, lx: 0, ly: 0, stars });
      Object.assign(scene, { w, h, fold: f, box: [Math.min(...stars.map((q) => q.x)) - 140, h / 2 - 160, Math.max(...stars.map((q) => q.x)) + 140, h / 2 + 160] });
      return;
    }
    // laid out as the approved mockup (starpulse#95, view C) lays it out in screen pixels: u world units a pixel at fit, F a pixel of text at the
    // reader's size. A template is drawn at up to 1.1 times its step graph, a wide fan cut to the mockup's apply-on-merge (141 x 104); a row's mini
    // graph at up to 0.55 of it (0.8 for one step), a fan cut to 59 x 43
    const raw = led.ties.map((t) => glyph(dagBy[t.dag] || stub(t.dag))), sc = (ctx.scale ?? 100) / 100, one = (g: Glyph) => g.nodes.length === 1;
    const tsc = raw.map((g) => (one(g) ? 1 : Math.min(1.1, 104 / Math.max(1, g.h), 141 / Math.max(1, g.w))));
    const msc = raw.map((g) => (one(g) ? 0.8 : Math.min(0.55, 43 / Math.max(1, g.h), 59 / Math.max(1, g.w))));
    const lines = (t: Tie) => [t.role === "writer" ? `on ${t.on}` : `cue · on ${t.on}`, ...(t.resolves ? [`clears on ${t.resolves === "forced" ? "forced rerun" : "next success"}`] : [])];
    const merges = led.rows === "merge" ? S.ledgers[led.event] ?? [] : [];
    // the gutter: the row labels' 340 px (at most a quarter of the level) when there are rows, else what the junction's label needs
    const lead = (u: number, F: number) => Math.max(F * (textW("merge to main", 12.5) + 88), merges.length ? 64 * u + Math.min(340 * F, 0.26 * w) : 0);
    const tw = (u: number) => raw.map((g, i) => g.w * tsc[i] * u + 2 * (one(g) ? 5 : 4) * u), base = (u: number, F: number) => tw(u).map((x) => x + 36 * F);
    const need = (u: number, F: number) => lead(u, F) + 46 * F + base(u, F).reduce((p, q) => p + q, 0) + 70 * u;
    // the level is the canvas's width, so a pixel is about a world unit; wider, and everything with it, when the templates and the gutter need more
    w = W;
    let u = 1, F = sc;
    for (let i = 0; i < 4 && need(u, F) > w; i++) [w, u, F] = [Math.ceil(need(u, F)), Math.ceil(need(u, F)) / W, (Math.ceil(need(u, F)) / W) * sc];
    h = Math.round(w / (W / H));
    const R = 22 * u, sx = lead(u, F), c0 = sx + 46 * F, dnx = w - 40 * u - 60 * F, avail = w - 70 * u - c0, widths = tw(u);
    const gl = raw.map((g, i) => scaled(g, tsc[i] * u)), gh = Math.max(...gl.map((g) => g.h)), th = Math.max(...gl.map((g) => g.h + 2 * (one(g) ? 5 : 4) * u)), cw = led.ties.map((t) => F * Math.max(textW(labelOf(t.dag), 12), ...lines(t).map((x) => textW(x, 10.5))));
    // each caption cell is its template plus what its caption needs past it, shrunk to share what the row has when they do not all fit, else spread across it
    const want = cw.map((c, i) => Math.max(0, c - widths[i])), basis = base(u, F);
    const free = avail - basis.reduce((p, q) => p + q, 0), wantSum = want.reduce((p, q) => p + q, 0), g = wantSum > free ? Math.max(0, free) / wantSum : 1, slack = Math.max(0, free - wantSum * g) / led.ties.length;
    // the bus sits under a template's name, two caption lines and the focused merge's status, with its own label clear of them
    const yP = 62 * F, yH = yP + 64 * F + th / 2, cap = yH + gh / 2 + 14 * F, bus = yH + gh / 2 + 88 * F;
    let x = c0;
    const cols = led.ties.map((t, i) => {
      const x0 = x, x1 = (x += basis[i] + want[i] * g + slack);
      return { ...t, x0, x1, y0: cap - 9 * F, y1: cap + 34 * F };
    });
    const end = (id: string, x: number): FoldEnd => ({ id, name: stateName(id), final: !!board.machine.states.find((s) => s.id === id)?.final, color: BOARD_COLOR[id] || "#94a3b8", x, y: yP, r: R });
    f.a = end(led.from, sx);
    f.b = end(led.to, dnx);
    f.p0 = { x: sx + R + 8 * u, y: yP };
    f.p1 = { x: dnx - R - 8 * u, y: yP };
    // a template sits at its column's left, as in the mockup, moved right only as far as keeps its centred caption inside the column
    const tx = cols.map((c, i) => Math.max(c.x0 + 14 * u + widths[i] / 2, c.x0 + Math.min(cw[i], c.x1 - c.x0 - 8 * F) / 2 + 4 * F));
    const stars = cols.map((c, i) => {
      const st = star(c.dag, tx[i], yH), via = `(${stateName(led.from)} → ${stateName(led.to)})`;
      st.glyph = gl[i];
      scene.stars[c.dag] = st;
      st.tether = { x: st.x, y: st.y, cue: c.role === "cue", crit: [c.role === "writer" ? `writes ${led.event} ${via}` : `runs on ${c.on}, beside ${led.event} ${via}`] };
      return st;
    });
    const writer = stars.find((_, i) => cols[i].role === "writer");
    f.ledger = { event: led.event, rows: led.rows, mark: { x: writer ? writer.x : (f.p0.x + f.p1.x) / 2, y: yP }, J: { x: sx, y: yH }, bus, cap, cols };
    scene.groups.push({ name: "", head: false, lx: 0, ly: 0, stars });
    let bottom = bus + 40 * F;
    if (merges.length) {
      // a row is one merge: its label in the gutter, then under each template its mini step graph beside the run's status line, at least the mockup's
      // 60 px tall and taller when a mini needs it. The viewport holds the rows that fit the level (and a footer row), so the fit box never outgrows it;
      // the rows beyond scroll through it (ledgerScroll)
      const nr = 3 * F, ms = msc.map((m, i) => m / tsc[i]), rh = Math.max(60 * u, 34 * F, ...gl.map((q, i) => q.h * ms[i] + 2 * nr + 12 * u));
      // the unresolved band takes the newest `cap` pins (at most half the rows that fit) and a gap off the viewport's top, and the 24-hour strip
      // sits 44 px under the viewport's last row, the mockup's, with its hour labels 30 px past that
      const top = bus + 26 * F, gap = 18 * F, under = 74 * F, room = h - top - 4 * F - under, held = new Set(merges.map((r) => r.key));
      const extra = (S.mergePins ?? []).filter((r) => !held.has(r.key)), fit0 = Math.max(1, Math.floor(room / rh)), fit1 = Math.max(1, Math.floor((room - gap) / rh));
      const cap = Math.max(1, Math.floor(fit1 / 2)), pins = pinsOf(merges, extra, cap).shown.length, fit = pins ? fit1 : fit0;
      const view = Math.min(fit, merges.length + extra.length + 1) * rh + (pins ? gap : 0);
      const cells = cols.map((c, i): GridCell => {
        const gx = tx[i], at = Math.max(gx + (gl[i].w * ms[i]) / 2 + nr + 12 * F, c.x0 + 30 * F);
        return { dag: c.dag, gx, ms: ms[i], tx: at, room: c.x1 - at - 10 * F };
      });
      const strip = { x0: sx, x1: w - 70 * u, y: top + view + 44 * F, h: 18 * F };
      f.ledger.grid = { rh, top, view, lane: sx + 22 * F, label: { x: 64 * u, w: sx - 74 * u }, nr, cells, gap, cap, pins, strip };
      bottom = strip.y + 30 * F;
    }
    Object.assign(scene, { w, h, fold: f, box: [0, 0, w, bottom] });
  }

  if (l.kind === "board") buildBoard();
  else if (l.kind === "state") {
    buildState(l.id);
    const top = topOf(SUBS, l);
    if (top) buildTop(top);
  } else if (l.kind === "fold") buildFold(l);
  else buildTop(l.flow, topOf(SUBS, { kind: "state", id: ctx.host ?? "" }) ?? Object.values(SUBS)[0]?.[0]);
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
