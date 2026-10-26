// Where everything on a level sits, ported from the approved round-13 mockup
// (the design mockup): the Board's states as galaxies with the
// DAGs as step-graph glyphs beside them, a state's lifecycle system as planets
// round its machine, one machine's states, the DAGs level, and a fold of DAGs over the Board path they write.
import type { HPlace } from "./transit";
import { topOf, type Fold, type Level } from "./levels";
import { ledgerTop, sizes as ledgerSizes, type LedgerTop } from "../features/level/machineLedger";
import { nestsOf } from "../features/level/machineChain";
import { laneRows, type LaneNode, type LaneRow } from "../features/level/machineLanes";
import { laneContent } from "../features/level/machineScroll";
import { shownRows, type Paging } from "../features/level/machinePaging";
import { rankRows } from "../features/level/machineRows";
import { ledgerOf, type Ledger, type Tie } from "../features/level/ledger";
import type { Viewport } from "../features/level/ledgerScroll";
import { countText, daily, HOUR, hosted, stale, stateCount, type Move, type Moves, type Sky } from "./sky";
import { pinsOf } from "../features/level/ledgerPins";
import type { Dag, DagStep, RawTask, Transition, Writer } from "../api";

export const TAU = Math.PI * 2;
export const BOARD_COLOR: Record<string, string> = { new: "#94a3b8", ready: "#60a5fa", waiting: "#fbbf24", blocked: "#fb7185", intoprogress: "#a78bfa",
  review: "#e879f9", needs_attention: "#64748b", done: "#34d399", completed: "#2dd4bf", archived: "#475569" };
/** Where a task's lifecycle ends, drawn as a black hole: a final Board state, Done once the board machine declares it final. A nested
 *  machine's final state is not one: it hands its task back to the state that runs the machine. */
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
  /** Where its paths end: just outside what it draws, which is its sun, its outermost ring of tasks or, where machines map, its moons' orbits. */
  edge: number;
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
  child: string;
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
  machine: string;
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
  machine: string;
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
  /** How far its rings spread, in screen px: a step's arrival stays small. */
  grow?: number;
}
/** A task orbiting its host; update() places it each frame. */
export interface Body extends RawTask {
  host: Host;
  R: number;
  a0: number;
  w: number;
  big: boolean;
  /** The dot's size against the usual one, smaller where a crowded cell packs it. */
  s?: number;
  x: number;
  y: number;
  ang: number;
  moving: boolean;
  arrive: Arrive | null;
  gone: boolean;
  via: string | null;
  hop?: { c: Curve; u: number };
  bev: Move[];
  /** The phase-machine step it rides, which transit.ts places and draws. */
  h?: HPlace;
  /** Its dot's opacity while it fades between suns no curve joins. */
  alpha?: number;
}
/** A task a lifecycle machine placed, drawn on the state its latest event left it in. */
export interface MachineTask extends RawTask {
  machine: string;
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
  /** Whether a merge Ledger's first page is still on its way: the rows are asked for when the Ledger opens. */
  loading?: boolean;
}
/** A fold's level: the DAGs one Board fold stands for. Over a Board path they are the Ledger of the event they are tied to, between the path's two states. */
export interface FoldView {
  a?: FoldEnd;
  b?: FoldEnd;
  p0?: Pt;
  p1?: Pt;
  ledger?: LedgerView;
}
/** A box on the Board's sky that a name prints in, which no path crosses: a state's name and count, or a machine's row out to its name's end. */
export interface NameBox {
  /** The state's id, or `state/machine` for a machine's row. */
  of: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
export interface Scene {
  w: number;
  h: number;
  /** The Board prints its moon names cut to NAME_MAX, so every state keeps its footprint whatever machines it holds. */
  clipped?: boolean;
  /** The Board's type scale against its 13 px state names: 0.45 of the sun's screen radius, 12 to 20 px. The page's text size multiplies it. */
  labelScale?: number;
  /** One screen pixel of type in sky units at the fitted zoom, the page's text size included: what a label's box is sized by before it draws. */
  px?: number;
  galaxies: Record<string, Galaxy>;
  bEdges: BEdge[];
  /** The Board's names, each in its box. */
  names: NameBox[];
  /** Every tied-DAG hangar's name and orbiters, each in its box, which the phase machines keep off. */
  hangars?: NameBox[];
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
  machine: string | null;
  pivot: Host | null;
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
  machine: string;
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
  /** A phase of the machine on top (blue) or another machine it opens (teal); none for a row that is neither. */
  kind?: "phase" | "sub";
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
/** Every Board state's sun, on the Board and on its own level: one fixed size, so neither its tasks nor its share of the moves resizes it. */
export const SUN_R = 34;
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

/** A sun's radius: `min` until its `n` tasks, `gap` apart on the ring `pad` outside it, would need a second ring; past that, the radius that holds them in one. */
export const oneRing = (n: number, gap: number, pad: number, min: number) => Math.max(min, Math.ceil((n * gap) / TAU) - pad);

const CLEAR = 20, HOLD = 16, NAME_CLEAR = 5, CROSS = 0.05, NAMED = 2, SKIM = 1, THROUGH = 50, NEAR = 10;
/**
 * The last Board's routed paths, keyed on everything that places them. A stream delta rarely moves a state, so the next Board reuses the
 * search instead of running it again on every task move.
 */
const last = { routes: { key: "", curves: [] as (Curve | null)[] } };
/**
 * Where a path bending through a point meets `g`'s rim: the point on the rim facing it. Where that point is in one of `rows`, the rows
 * `g`'s machines print their names in, the path meets the rim at the nearest point round it, in steps of 2°, that is in none.
 */
const rimOf = (g: Galaxy, rows: NameBox[] = []) => {
  const on = (t: number) => ({ x: g.x + Math.cos(t) * g.edge, y: g.y + Math.sin(t) * g.edge });
  const shut = (p: Pt) => rows.some((n) => p.x > n.x0 - NAME_CLEAR && p.x < n.x1 + NAME_CLEAR && p.y > n.y0 - NAME_CLEAR && p.y < n.y1 + NAME_CLEAR);
  // every spot on the sky asks, so the rim is read once, a degree at a time, the first time a path faces a row; a step then looks its
  // angle up before it is measured
  let open: boolean[] | undefined;
  const free = (t: number) => {
    if (!open![((Math.round((t * 180) / Math.PI) % 360) + 360) % 360]) return null;
    const p = on(t);
    return shut(p) ? null : p;
  };
  return (c: Pt) => {
    const at = Math.atan2(c.y - g.y, c.x - g.x), p = on(at);
    if (!rows.length || !shut(p)) return p;
    open ||= Array.from({ length: 360 }, (_, k) => !shut(on((k * Math.PI) / 180)));
    for (let i = 1; i <= 45; i++) {
      const q = free(at + (i * Math.PI) / 90) ?? free(at - (i * Math.PI) / 90);
      if (q) return q;
    }
    return p;
  };
};
/** The rows a state's machines print their names in, of all the names on the Board. */
const rowsOf = (g: Galaxy, names: NameBox[]) => names.filter((n) => n.of.startsWith(`${g.id}/`));
/**
 * Whether a path meets the line `u = at` between `lo` and `hi` on the other axis: `a`, `b` and `c` are the path's quadratic along `u`
 * (a·t² + b·t + c), `a2`, `b2` and `c2` its quadratic along the other axis.
 */
const meets = (a: number, b: number, c: number, a2: number, b2: number, c2: number, at: number, lo: number, hi: number) => {
  const within = (t: number) => {
    const v = (a2 * t + b2) * t + c2;
    return t >= 0 && t <= 1 && v > lo && v < hi;
  };
  if (Math.abs(a) < 1e-9) return Math.abs(b) > 1e-9 && within((at - c) / b);
  const d = b * b - 4 * a * (c - at);
  return d >= 0 && (within((-b + Math.sqrt(d)) / (2 * a)) || within((-b - Math.sqrt(d)) / (2 * a)));
};
/**
 * A Board path between two states. It keeps CLEAR px from every other state's footprint, out of what its own two draw, and NAME_CLEAR
 * from the names in `names`, its own two states' included. Where the path from `c0` would not, its control point moves to a spot on the
 * sky; each spot costs its bend from `c0` and what its path runs over, counted as the bend it is worth to avoid: NAMED for a name, SKIM
 * for a state's footprint, THROUGH for what a state draws (twice that at its centre), and CROSS for each point of it on a path already drawn. The cheapest spot
 * wins, so a path that can clear everything takes the least bend that does, and one that cannot runs over the least it can. `sky` bounds
 * the path; its control point stays on it unless every such spot still runs through a state's body, when it may lie beyond any edge, up to the
 * sky's own size past it, as far as the path itself stays on the sky. `held` is the bend the path took last, which it keeps while that stays
 * out of every name and CLEAR - NAME_CLEAR from every other footprint.
 */
export function routed(a: Galaxy, b: Galaxy, c0: Pt, all: Galaxy[], drawn: Drawn, sky: Pt, held?: Pt, names: NameBox[] = []): Curve {
  const others = all.filter((g) => g !== a && g !== b), from = rimOf(a, rowsOf(a, names)), to = rimOf(b, rowsOf(b, names));
  const shape = (c: Pt): Curve => ({ p0: from(c), c, p1: to(c) });
  /** What a path runs over, with `by` the room it leaves a footprint: counted only up to `cap`, past which the path is already beaten. */
  const over = ({ p0, c, p1 }: Curve, by = CLEAR, cap = Infinity) => {
    // a path lies inside the box of its three points, so only a state or a name whose margin reaches that box can be in its way
    const x0 = Math.min(p0.x, c.x, p1.x), x1 = Math.max(p0.x, c.x, p1.x), y0 = Math.min(p0.y, c.y, p1.y), y1 = Math.max(p0.y, c.y, p1.y);
    const near = others.filter((g) => g.x + g.R + by > x0 && g.x - g.R - by < x1 && g.y + g.R + by > y0 && g.y - g.R - by < y1), deep = near.map(() => 0);
    let n = 0, own = 0;
    // the states are tested at the points sample() would give, without allocating them: every spot on the sky runs this
    for (let i = 0; i <= 48; i++) {
      const t = i / 48, u = 1 - t, x = u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, y = u * u * p0.y + 2 * u * t * c.y + t * t * p1.y;
      for (let j = 0; j < near.length; j++) {
        const g = near[j], d = (x - g.x) ** 2 + (y - g.y) ** 2, reach = g.edge + NEAR;
        // what a state draws costs more the nearer its centre the path runs, so a path that cannot clear it still takes the shallowest cut
        const into = d < reach ** 2 ? THROUGH * (2 - Math.sqrt(d) / reach) : d < (g.R + by) ** 2 ? SKIM : 0;
        if (into > deep[j]) {
          n += into - deep[j];
          deep[j] = into;
        }
      }
      if (!own && ((x - a.x) ** 2 + (y - a.y) ** 2 < (a.edge - 2) ** 2 || (x - b.x) ** 2 + (y - b.y) ** 2 < (b.edge - 2) ** 2)) n += own = THROUGH;
      if (n >= cap) return n;
    }
    // a name is thinner than the step between two of those points, so the path itself is tested: it enters a box it does not start in
    // only across one of the box's four sides
    const pad = NAME_CLEAR + by - CLEAR, ax = p0.x - 2 * c.x + p1.x, bx = 2 * (c.x - p0.x), ay = p0.y - 2 * c.y + p1.y, by2 = 2 * (c.y - p0.y);
    for (const k of names) {
      const l = k.x0 - pad, r = k.x1 + pad, t = k.y0 - pad, d = k.y1 + pad;
      if (r <= x0 || l >= x1 || d <= y0 || t >= y1) continue;
      if ((p0.x > l && p0.x < r && p0.y > t && p0.y < d) || meets(ax, bx, p0.x, ay, by2, p0.y, l, t, d) || meets(ax, bx, p0.x, ay, by2, p0.y, r, t, d) || meets(ay, by2, p0.y, ax, bx, p0.x, t, l, r) || meets(ay, by2, p0.y, ax, bx, p0.x, d, l, r)) n += NAMED;
      if (n >= cap) return n;
    }
    return n;
  };
  /** The paths drawn that `e` crosses, counted only while they can still bring it under `cap`. */
  const crossings = ({ p0, c, p1 }: Curve, cap: number) => {
    let n = 0;
    for (let i = 0; i <= 30 && n < cap; i++) {
      const t = i / 30, u = 1 - t;
      if (drawn.near(u * u * p0.x + 2 * u * t * c.x + t * t * p1.x, u * u * p0.y + 2 * u * t * c.y + t * t * p1.y)) n++;
    }
    return n;
  };
  // a bent path straightens only once the straight path clears by HOLD more, and keeps its bend while that clears by NAME_CLEAR less than a
  // new bend must, so a count gaining a digit or a ring of tasks filling beside the path never hops it to another spot and back
  const straight = shape(c0);
  if (!over(straight, held ? CLEAR + HOLD : CLEAR)) return straight;
  if (held && !over(shape(held), CLEAR - NAME_CLEAR)) return shape(held);
  // the spots are tried nearest first, equals in sky order, until the next is further than the best costs. That is a few dozen in for most
  // paths, so the search takes the spots a band of bend at a time (each band twice as wide as the last, so a spot is measured once more at
  // most) and sorts only the band it reaches
  /** Whether a spot is on the sky: a path bowed to one is the nearest the search looks. */
  const fit = (c: Pt) => c.x >= 10 && c.y >= 10 && c.x <= sky.x - 10 && c.y <= sky.y - 10;
  /** Whether the path stays on the sky (or where its own two ends already are): the far points of its bow, where it turns, are inside. */
  const onSky = ({ p0, c, p1 }: Curve) => {
    const span = (u0: number, uc: number, u1: number) => {
      const d = u0 - 2 * uc + u1, t = d ? (u0 - uc) / d : -1, mid = t > 0 && t < 1 ? (1 - t) ** 2 * u0 + 2 * t * (1 - t) * uc + t * t * u1 : u0;
      return [Math.min(u0, u1, mid), Math.max(u0, u1, mid)];
    };
    const [x0, x1] = span(p0.x, c.x, p1.x), [y0, y1] = span(p0.y, c.y, p1.y);
    return x0 >= Math.min(10, p0.x, p1.x) && x1 <= Math.max(sky.x, p0.x, p1.x) && y0 >= Math.min(10, p0.y, p1.y) && y1 <= Math.max(sky.y, p0.y, p1.y);
  };
  let best = straight, cost = over(straight) + CROSS * crossings(straight, Infinity);
  /** The spots of the lattice between `lo` and `hi` that `take` keeps, cheapest-bend first, over the best so far. */
  const search = (lo: Pt, hi: Pt, take: (c: Pt) => boolean) => {
    const cols = [Math.ceil((lo.x - 10) / 40), Math.floor((hi.x - 10) / 40)], rows = [Math.ceil((lo.y - 10) / 40), Math.floor((hi.y - 10) / 40)];
    const reach = Math.hypot(Math.max(c0.x - lo.x, hi.x - c0.x), Math.max(c0.y - lo.y, hi.y - c0.y)) / 200;
    for (let near = 0, far = 0.5; near < cost && near <= reach; near = far, far *= 2) {
      const band: { c: Pt; bend: number }[] = [], r = far * 200;
      // the lattice columns and rows within r of c0, one more each side than the arithmetic needs
      const kx = [Math.max(cols[0], Math.ceil((c0.x - r - 10) / 40) - 1), Math.min(cols[1], Math.floor((c0.x + r - 10) / 40) + 1)];
      const ky = [Math.max(rows[0], Math.ceil((c0.y - r - 10) / 40) - 1), Math.min(rows[1], Math.floor((c0.y + r - 10) / 40) + 1)];
      for (let i = kx[0]; i <= kx[1]; i++)
        for (let j = ky[0]; j <= ky[1]; j++) {
          const c = { x: 10 + 40 * i, y: 10 + 40 * j }, bend = Math.hypot(c.x - c0.x, c.y - c0.y) / 200;
          if (bend >= near && bend < far && take(c)) band.push({ c, bend });
        }
      for (const { c, bend } of band.sort((p, q) => p.bend - q.bend)) {
        if (bend >= cost) break;
        const e = shape(c);
        if (!fit(c) && !onSky(e)) continue;
        const base = bend + over(e, CLEAR, cost - bend);
        if (base >= cost) continue;
        const total = base + CROSS * crossings(e, (cost - base) / CROSS);
        if (total < cost) [cost, best] = [total, e];
      }
    }
  };
  search({ x: 10, y: 10 }, { x: sky.x - 10, y: sky.y - 10 }, fit);
  // a path that still runs through what a state draws may bow beyond the sky, as far out as the sky is wide and tall on every side, where
  // the path itself stays on it: a bend there clears what none on the sky can
  if (cost >= THROUGH) search({ x: -sky.x, y: -sky.y }, { x: sky.x * 2, y: sky.y * 2 }, (c) => !fit(c));
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

/**
 * A Board state's footprint in sky units, at the sun's own size (SUN_R): its tasks ring the sun from task0 to task1, a moon and its tasks reach
 * `moon`, a sub-state and its tasks `sub`. Every state takes the same one, busy or empty; MOONS moons sit on its ring where machines map.
 */
const FOOT = { task0: SUN_R + 14, task1: SUN_R + 38, moon: 18, sub: 16 };
/** The least dot and ring gap a Board state's tasks keep, so a pointer can pick one: a state too full for its band at this gap widens it. */
const ROOM = 8;
/** How far past task1 a Board state's band widens to hold `n` tasks ROOM apart; none while they fit. */
const widen = (n: number) => Math.max(0, rings(n, FOOT.task0, ROOM, ROOM).outer - FOOT.task1);
/** The machines a Board state's ring holds before the rest page: its primary and the MOONS - 1 on the page. */
export const MOONS = 8;
/** The Board's greatest zoom: the sun is today's size, so a Board of a few states grows to fill the canvas only this far. */
const ZOOM_MAX = 16;
/**
 * The dot and ring gaps that hold `n` bodies in rings from r0 out to r1: a fuller body adds rings inside its band, closer together, never past it,
 * and never closer than `least`.
 */
function pack(n: number, r0: number, r1: number, gap: number, ringGap: number, least = 2.5) {
  for (let g = gap; g >= 3; g -= 0.5)
    for (let m = 1; m < 64; m++) {
      const rg = m > 1 ? Math.min(ringGap, (r1 - r0) / (m - 1)) : ringGap;
      if (rg < least - 0.01) break;
      if (rings(n, r0, g, rg).outer <= r1 + 0.01) return { gap: g, ringGap: rg };
    }
  return { gap: 3, ringGap: 2.5 };
}
/** The Board's type scale at zoom k: a state's name is 0.45 of its sun's screen radius, 12 to 20 px, against the 13 px it is drawn at. */
const labelScale = (k: number) => Math.min(20, Math.max(12, 0.45 * SUN_R * k)) / 13;
/**
 * The number of lines to wrap the Board's tiers into, given the zoom each count allows (one line first). The sun is the same size in every
 * line count, so the zoom is what a wrap buys: it wraps only when that is more than 5% larger than the best before it.
 */
export function pickRows(zooms: number[]): number {
  let best = 0, rows = 1;
  zooms.forEach((k, i) => {
    if (k > 1.05 * best) {
      best = k;
      rows = i + 1;
    }
  });
  return rows;
}

export const PAGE_SIZE = 12;

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
  const scene: Scene = { w: 2460, h: 1340, galaxies: {}, bEdges: [], names: [], tasks: [], machineTasks: [], mStates: {}, mEdges: [], planets: [], moons: [], subStates: [], stars: {}, groups: [], sun: null, machine: null, pivot: null, hops: [], entries: [], exits: [] };
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
  const attach = (list: RawTask[], host: Host, r0: number, gap: number, ringGap: number, big: boolean, speed = 1) => {
    const o = rings(list.length, r0, gap, ringGap);
    list.forEach((a, i) => scene.tasks.push({ ...a, host, ...o.slots[i], w: o.slots[i].w * speed, big, x: host.x, y: host.y, ang: 0, moving: false, arrive: null, gone: false, via: null, bev: [] }));
    host.rings = o.radii;
    return o.outer;
  };
  function buildBoard() {
    // The Board's places come from its machine and its declared main line: the columns it draws when no tiers are configured.
    const states = board.machine.states, transitions = board.machine.transitions;
    const BP = boardPlaces(states, transitions, board.machine.mainLine ?? undefined);
    const byState: Record<string, RawTask[]> = {};
    // a starting state orbits no task, as each is drawn where it went; a terminal state orbits those that entered it since local midnight and the day's
    // arrivals there not already in it
    const initial = new Set(states.filter((s) => s.initial).map((s) => s.id)), final = new Set(states.filter((s) => s.final).map((s) => s.id));
    board.agents.forEach((a) => initial.has(a.state) || stale(S, a) || (byState[a.state] ||= []).push(a));
    for (const [sid, list] of Object.entries(S.today)) if (final.has(sid)) (byState[sid] ||= []).push(...list.filter((t) => !byState[sid]?.some((a) => a.id === t.id)));
    // A task orbits the deepest body this level draws that it is in: the sub-state its latest session holds (a CHILD entry, pr_opened while a PR
    // is open), else the moon of the machine it works when that is not its state's primary, else its state.
    const flowsOf = (sid: string) => (SUBS[sid] || []).filter((f) => S.flows[f]);
    const subStatesOf = (f: string) => S.flows[f].machine.states.filter((q) => S.child[f]?.[q.id]);
    const deepest = (a: RawTask): { flow: string; state?: string } | null => {
      const q = S.latest[a.id], fs = flowsOf(a.state);
      if (a.today || !q || !fs.includes(q.flow)) return null;
      if (S.child[q.flow]?.[q.state]) return { flow: q.flow, state: q.state };
      return fs.indexOf(q.flow) > 0 ? { flow: q.flow } : null;
    };
    // One sky unit is `1 / k` screen pixels at the Board's zoom k, so a name printed at a screen size takes F sky units a pixel.
    let F = 1;
    // A state's footprint is fixed until its tasks would sit closer than ROOM, when its band widens by just enough: the sun and its `n` tasks in
    // rings packed into the band round it. Its machines are drawn only while they run, as branches off it (transit.ts), so they reserve no ring of
    // their own.
    const FREE = SUN_R + 7, MOON_RING = 104;
    const footprint = (moons: boolean, n: number) => {
      const more = widen(n);
      if (!moons) {
        const band = FOOT.task1 + more, R = band + 6;
        return { moonR: band, R, reach: [R, R] as [number, number], band };
      }
      const side = MOON_RING + more + 12 + textW("x".repeat(NAME_MAX), 9.5) * F;
      return { moonR: MOON_RING + more, R: MOON_RING + more + 22, reach: [side, side] as [number, number], band: FOOT.task1 + more };
    };
    // A state's primary machine whose states open child machines is drawn as its phases: each phase's steps are its child's states.
    const phasesOf = (sid: string) => {
      const f = flowsOf(sid)[0];
      if (!f) return [];
      // a phase opening several machines (Deliver opens deliver and triaging-cr-reviews) steps through the one named for it; the others are side machines
      return subStatesOf(f).map((q) => {
        const kids = (S.tree.children[f] ?? []).filter((c) => c.state === q.id), main = kids.find((c) => c.machine === q.id) ?? kids[0];
        return { q, child: { machine: main.machine, when: main.when && `while ${main.when}` }, side: kids.filter((c) => c !== main).map((c) => c.machine), steps: S.flows[main.machine]?.machine.states ?? [] };
      }).filter((p) => p.steps.length);
    };
    const phased = (sid: string, ps: ReturnType<typeof phasesOf>, a: RawTask) => {
      const q = S.latest[a.id], f = flowsOf(sid)[0];
      return !!q && !a.today && ps.some((p) => (q.flow === f && p.q.id === q.state) || p.child.machine === q.flow);
    };
    const radius = (st: (typeof states)[number]) => {
      const all = byState[st.id] || [], fs = flowsOf(st.id), ps = phasesOf(st.id), sides = ps.flatMap((p) => p.side);
      // the sun's own tasks: none in a phase, a side machine or a lifecycle's sub-state
      const here = all.filter((a) => !sides.includes(S.latest[a.id]?.flow ?? "") && !phased(st.id, ps, a) && !deepest(a)), foot = footprint(false, here.length);
      // the sky is laid out from the footprint the machines' moons once reserved, so the suns keep the places the Board has always given them
      const was = footprint(fs.length > 0, here.length), lay = { R: was.R, reach: fs.length ? was.reach : null };
      return { r: SUN_R, R: foot.R, band: foot.band, lay, ps, here };
    };
    // The grid: the Board's tiers are its cells, in order, in `rows` lines of them wrapping left to right, a tier's states stacked top to
    // bottom in its cell. The tiers are the board machine's configured `tiers` (the states drawn at each stage, left to right); with none
    // configured, the Board's own columns (the states it draws at one place across). A state no tier names is drawn with the tier at the mean
    // of those its paths join it to, or in a tier of its own after the last when none does. A cell is as wide as its widest state's footprint
    // and a line as tall as its tallest cell, like a CSS grid's auto tracks, and the room left over is shared evenly between the cells across
    // and the lines down.
    const ids = new Set(states.map((st) => st.id)), conf = board.machine.tiers?.length ? board.machine.tiers : null;
    const across = [...new Set(states.map((st) => BP[st.id][0]))].sort((a, b) => a - b);
    const tierOf = new Map<string, number>();
    conf?.forEach((t, i) => t.forEach((id) => ids.has(id) && !tierOf.has(id) && tierOf.set(id, i)));
    // An unnamed state its paths join to named ones takes the tier at the mean of theirs: stacked in it, or in a tier of its own after it,
    // whichever draws the sun larger; one no path joins takes a tier of its own after the last.
    const pull = new Map<string, number>(), loose: string[] = [];
    for (const st of conf ? states.filter((q) => !tierOf.has(q.id)) : []) {
      const joined = transitions.flatMap((t) => [t.source === st.id ? tierOf.get(t.target) : undefined, t.target === st.id ? tierOf.get(t.source) : undefined]).filter((i) => i !== undefined);
      if (joined.length) pull.set(st.id, Math.round(joined.reduce((t, i) => t + i, 0) / joined.length));
      else loose.push(st.id);
    }
    const ix = new Map(states.map((st, i) => [st.id, i]));
    const declared = conf ?? across.map((x) => states.map((st) => st.id).filter((id) => BP[id][0] === x).sort((a, b) => BP[a][1] - BP[b][1]));
    const lone = (i: number) => declared[i]?.length === 1;
    // A state's slot is where its tier names it, so it keeps its place when a state it is stacked with is absent: the tier holds the slot empty.
    // A tier of one state beside another such tier takes the high or low slot its id's character codes give, so it stays put whichever tiers
    // come or go; with no such tier beside it, it sits mid-height. A state no tier names takes the slots after its tier's.
    type Slot = { i: number; at: number; n: number; of: number };
    const grid = (stack: boolean) => {
      const into = new Map<number, string[]>(), after = new Map<number, string[]>();
      const last = (declared.length || 1) - 1;
      for (const [id, k] of pull) (stack ? into : after).set(k, [...((stack ? into : after).get(k) ?? []), id]);
      if (loose.length) after.set(last, [...(after.get(last) ?? []), ...loose]);
      const slot = new Map<string, Slot>(), cols: string[][] = [];
      declared.forEach((t, i) => {
        const guests = into.get(i) ?? [];
        cols.push([...t, ...guests].filter((id) => ids.has(id)));
        t.forEach((id, at) => ids.has(id) && !slot.has(id) && slot.set(id, { i, at, n: t.length, of: t.length + guests.length }));
        guests.forEach((id, j) => slot.set(id, { i, at: t.length + j, n: t.length, of: t.length + guests.length }));
        for (const id of after.get(i) ?? []) {
          cols.push([id]);
          slot.set(id, { i: i + 0.5, at: 0, n: 1, of: 1 });
        }
      });
      return { cols: cols.filter((t) => t.length), slot };
    };
    type Grid = ReturnType<typeof grid>;
    // with no tiers configured, the Board's own columns alternate along a run of single-state ones, each by its place in the run
    const runSide = new Map<string, number>();
    let run = 0;
    declared.forEach((t, i) => {
      run = lone(i) && (lone(i - 1) || lone(i + 1)) ? run + 1 : 0;
      if (run) runSide.set(t[0], (run - 1) % 2);
    });
    const sideOf = (g: Grid, id: string) => {
      const { i } = g.slot.get(id)!, beside = Number.isInteger(i) ? [i - 1, i + 1] : [Math.floor(i), Math.ceil(i)];
      if (!conf) return runSide.get(id) ?? -1;
      return beside.some(lone) ? [...id].reduce((t, ch) => t + ch.charCodeAt(0), 0) % 2 : -1;
    };
    // what a state's cell takes either side of its centre: its footprint, at least half its name's width, and above it the room for that name
    const NAME_ROOM = 34;
    // a tier's states stacked in the slots it names them in, a tier of one state in the high or low of two, so its moon names tuck above or
    // below its neighbour's; a tier's sun stays right of the last one's, by at least the larger of their rings
    const gridLay = (grid: Grid, es: { l: number; r: number; t: number; b: number }[], rows: number, sw: number, sh: number, gap: number) => {
      const { cols, slot } = grid, per = Math.ceil(cols.length / rows), xs = states.map(() => 0), ys = states.map(() => 0);
      const lines = Array.from({ length: rows }, (_, j) => cols.slice(j * per, (j + 1) * per)).filter((l) => l.length);
      const e = (id: string) => es[ix.get(id)!], sum = (v: number[]) => v.reduce((t, x) => t + x, 0);
      const hOf = (id: string) => e(id).t + e(id).b + gap;
      // the ids whose footprints a tier's slots take, an empty slot the tier's tallest: a tier's room is the same with a state absent
      const slotsOf = (u: string[]) => {
        const { n } = slot.get(u[0])!, total = Math.max(...u.map((id) => slot.get(id)!.of)), one = n === 1 && total === 1;
        const host = u.filter((id) => slot.get(id)!.at < n), side = n === 1 && host.length ? sideOf(grid, host[0]) : -1;
        const own = new Map<number, string>();
        host.forEach((id) => own.set(n > 1 ? slot.get(id)!.at : Math.max(side, 0), id));
        let next = 0;
        for (const id of u.filter((q) => slot.get(q)!.at >= n)) {
          while (own.has(next)) next++;
          own.set(next, id);
        }
        const tall = u.reduce((a, id) => (hOf(id) > hOf(a) ? id : a));
        return { own, slots: one && side < 0 ? [u[0]] : Array.from({ length: Math.max(2, total) }, (_, i) => own.get(i) ?? tall), one };
      };
      const uh = (u: string[]) => {
        const t = slotsOf(u);
        return sum((t.one ? [u[0]] : t.slots).map(hOf));
      };
      const lh = lines.map((l) => Math.max(...l.map(uh))), fy = (sh - sum(lh)) / lines.length;
      const at = (id: string) => ix.get(id)!, up = (id: string) => ys[at(id)] - e(id).t - gap / 2, dn = (id: string) => ys[at(id)] + e(id).b + gap / 2;
      let y0 = 0, ok = fy >= 0;
      lines.forEach((l, j) => {
        const band = lh[j] + fy;
        l.forEach((u) => {
          const { own, slots } = slotsOf(u), free = (band - sum(slots.map(hOf))) / (slots.length + 1);
          let y = y0 + free;
          slots.forEach((id, n) => {
            if (own.get(n) === id) ys[at(id)] = y + gap / 2 + e(id).t;
            y += hOf(id) + free;
          });
        });
        // left to right: each tier as far left as its states clear every state placed before them that they share height with
        const cx: number[] = [], done: string[] = [];
        l.forEach((u, c) => {
          let x = Math.max(...u.map((id) => e(id).l + gap / 2));
          for (const id of u)
            for (const a of done) {
              const meet = up(a) < dn(id) && up(id) < dn(a);
              if (meet) x = Math.max(x, cx[l.findIndex((v) => v.includes(a))] + e(a).r + gap + e(id).l);
              else if (l[c - 1]?.includes(a)) x = Math.max(x, cx[c - 1] + Math.max(e(a).b, e(id).b));
            }
          cx.push(x);
          done.push(...u);
        });
        const lw = cx[l.length - 1] + Math.max(...l[l.length - 1].map((id) => e(id).r + gap / 2)), fx = (sw - lw) / l.length;
        ok &&= lw <= sw;
        l.forEach((u, c) => u.forEach((id) => (xs[at(id)] = cx[c] + fx * (c + 0.5))));
        y0 += band;
      });
      return { xs, ys, ok };
    };
    // The Board laid out at zoom `k` in `rows` lines: the sky is the canvas over `k`, and the layout holds when no two cells meet and every
    // line fits
    const lay = (grid: Grid, k: number, rows: number) => {
      const ls = labelScale(k);
      F = (ls * ((ctx.scale ?? 100) / 100)) / k;
      const sized = Object.fromEntries(states.map((st) => [st.id, radius(st)])), sw = (0.94 * W) / k, sh = (0.94 * H) / k, gap = 16 / k;
      // a state reaches at least half its name's width either side, so two names at one height never run together
      const es = states.map((st) => {
        const s = sized[st.id].lay, half = textW(stateName(st.id), 13 * F) / 2;
        return { l: Math.max(half, s.reach?.[1] ?? s.R), r: Math.max(half, s.reach?.[0] ?? s.R), t: s.R + NAME_ROOM * F, b: s.R };
      });
      const g = gridLay(grid, es, rows, sw, sh, gap);
      const ps = states.map((st, i) => ({ id: st.id, R: sized[st.id].lay.R, x: g.xs[i], y: g.ys[i] }));
      const box = (i: number) => [ps[i].x - es[i].l - gap / 2, ps[i].y - es[i].t - gap / 2, ps[i].x + es[i].r + gap / 2, ps[i].y + es[i].b + gap / 2];
      // every state, its name above and its rings and moons round it lie inside the sky, as well as clear of each other
      let ok = g.ok && ps.every((q, i) => q.x - es[i].l >= 0 && q.x + es[i].r <= sw && q.y - es[i].t >= 0 && q.y + es[i].b <= sh);
      for (let i = 0; ok && i < ps.length; i++)
        for (let j = i + 1; ok && j < ps.length; j++) {
          const a = box(i), b = box(j);
          if (a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]) ok = false;
        }
      return { ok, sized, ps, sw, sh, ls };
    };
    // the largest zoom, up to ZOOM_MAX, at which `rows` lines hold the Board
    const zoom = (grid: Grid, rows: number) => {
      let lo = 0.05, hi = ZOOM_MAX;
      for (let i = 0; i < 30; i++) {
        const m = (lo + hi) / 2;
        if (lay(grid, m, rows).ok) lo = m;
        else hi = m;
      }
      return lo;
    };
    const best = (pull.size ? [grid(true), grid(false)] : [grid(false)])
      .map((g) => {
        const zooms = g.cols.map((_, i) => zoom(g, i + 1)), rows = pickRows(zooms);
        return { g, rows, k: zooms[rows - 1] };
      })
      .reduce((a, b) => (b.k > a.k + 1e-9 ? b : a));
    const rows = best.rows, L = lay(best.g, best.k, rows);
    // each state's place and the sky's width ease toward the layout's targets, so a state changing size moves its neighbours and the fit smoothly
    for (const p of L.ps) {
      p.x = ease(`${p.id}.x`, p.x);
      p.y = ease(`${p.id}.y`, p.y);
    }
    const w = ease("sky.w", L.sw);
    scene.w = w;
    scene.h = Math.round(w / (W / H));
    scene.clipped = true;
    scene.labelScale = L.ls;
    scene.px = (ctx.scale ?? 100) / 100 / best.k;
    const sized = L.sized, ps = L.ps, hb = scene.h - 40;
    for (const st of states) {
      const p = ps.find((q) => q.id === st.id)!, { x, y } = p, { ps: phs, here, band: outer } = sized[st.id], r = ease(`${st.id}.r`, sized[st.id].r), R = ease(`${st.id}.R`, sized[st.id].R);
      const g: Galaxy = { id: st.id, name: st.name, x, y, r, n: stateCount(S, st.id), color: BOARD_COLOR[st.id] ?? "#94a3b8", final: st.final, today: daily(st) ? (S.today[st.id] ?? []).length : undefined, subs: SUBS[st.id] || [], R, moonR: 0, visR: 0, edge: R, lab: { x, y }, reach: [R, R], loops: [] };
      const r0 = phs.length ? FREE : FOOT.task0, r1 = phs.length ? SUN_R + 12 : outer;
      // a task on a machine step rides that machine's branch (transit.ts places it); only the rest orbit the sun
      const hOf = new Map<RawTask, HPlace>(), f0 = flowsOf(st.id)[0];
      if (f0)
        for (const a of byState[st.id] || []) {
          const q = S.latest[a.id];
          if (!q || a.today) continue;
          const ph = phs.find((p) => q.flow === f0 && p.q.id === q.state), sd = phs.find((p) => p.side.includes(q.flow)), m = S.flows[q.flow]?.machine.states.map((x) => x.id);
          if (ph) hOf.set(a, { machine: ph.child.machine, steps: ph.steps.map((x) => x.id), j: 0, ring1: true });
          else if (m) hOf.set(a, { machine: q.flow, steps: m, j: Math.max(0, m.indexOf(q.state)), config: [q.state], ring1: !phs.length || phs.some((p) => p.child.machine === q.flow), side: sd && { machine: sd.child.machine, steps: sd.steps.map((x) => x.id), j: Math.max(0, sd.steps.findIndex((x) => x.id === "pr_opened")) } });
        }
      const free = (byState[st.id] || []).filter((a) => !hOf.has(a) && (!a.today || here.includes(a)));
      const fit = pack(free.length, r0, r1, 11, 12, ROOM), ring = free.length ? attach(free, g, r0, fit.gap, fit.ringGap, false) : sized[st.id].r;
      g.moonR = ease(`${st.id}.moonR`, outer + 16);
      g.edge = ease(`${st.id}.edge`, f0 ? Math.max(52, ring + 10) : ring + 10);
      g.visR = outer + 7; // a task hopping in orbits on the outer edge
      scene.galaxies[st.id] = g;
      for (const [a, h] of hOf) scene.tasks.push({ ...a, host: g, R: 0, a0: 0, w: 0, big: false, s: 1, x, y, ang: 0, moving: false, arrive: null, gone: false, via: null, bev: [], h });
    }
    // a state's name goes above its footprint, in the room its cell keeps for it, its count under it
    const gs = Object.values(scene.galaxies);
    for (const g of gs) {
      g.lab = { x: g.x, y: g.y - g.R - 14 - 38 * F + 12 };
      const half = Math.max(textW(g.name, 13 * F), textW(`${countText(g.n, g.today)}${g.subs.length ? ` · ${g.subs.length} lifecycles` : ""}`, 11 * F)) / 2;
      scene.names.push({ of: g.id, x0: g.x - half, y0: g.lab.y - 7 * F, x1: g.x + half, y1: g.lab.y + 20 * F });
    }
    // One path per ordered pair of states, carrying every event between them. A pair joined both ways bows to one side, its two paths drawn
    // as one, and a one-way path runs straight. A final state reached from several states (Archived) gathers its one-way paths into one
    // stream along its side of the Board; a pair joined both ways into it keeps its shared line. Then any path that would pass another state or cross a name bends away until it clears (routed).
    const pairs = merged(transitions, S.writers);
    const routeKey = JSON.stringify([w, hb, gs.map((g) => [g.id, g.x, g.y, g.R, g.edge, g.final]), scene.names, pairs.map((t) => [t.source, t.target]), [...routes]]);
    const reuse = last.routes.key === routeKey, curves: (Curve | null)[] = [];
    const drawn = new Drawn(), there = new Map<string, Curve>();
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
      const gathers = b.final && !both && new Set(transitions.filter((t) => t.target === b.id && t.source !== b.id).map((t) => t.source)).size > 1;
      const c0 = gathers ? { x: a.x + dx * 0.15, y: b.y } : { x: (a.x + b.x) / 2 - (dy / L) * L * side, y: (a.y + b.y) / 2 + (dx / L) * L * side };
      // a bend is kept in the frame of its two states (u along a→b, v across it), so a held route moves with them
      const k = `${tr.source}>${tr.target}`, h = routes.get(k), held = h && { x: a.x + h.x * dx - h.y * dy, y: a.y + h.x * dy + h.y * dx };
      // a pair joined both ways is one path: the way back takes the way there
      const back = there.get(`${tr.target}>${tr.source}`);
      const r = reuse ? last.routes.curves[curves.length] : back ? { p0: back.p1, c: back.c, p1: back.p0 } : routed(a, b, c0, gs, drawn, { x: w, y: hb }, held, scene.names);
      curves.push(r);
      there.set(k, r!);
      if (!reuse && !back) drawn.add(sample(r!, 30));
      const ox = r!.c.x - a.x, oy = r!.c.y - a.y, u0 = (ox * dx + oy * dy) / L ** 2, v0 = (oy * dx - ox * dy) / L ** 2;
      if (Math.hypot(r!.c.x - c0.x, r!.c.y - c0.y) < 0.5) routes.delete(k);
      else routes.set(k, { x: u0, y: v0 });
      // the bend eases in that frame, so the path rides its states as they move, a re-route bends it over to its new shape instead of
      // snapping, and its ends stay on the rims facing the bend
      const u = ease(`${k}.u`, u0), v = ease(`${k}.v`, v0);
      const c = { x: a.x + u * dx - v * dy, y: a.y + u * dy + v * dx };
      scene.bEdges.push({ ...tr, p0: rimOf(a, rowsOf(a, scene.names))(c), c, p1: rimOf(b, rowsOf(b, scene.names))(c) });
    }
    last.routes = { key: routeKey, curves };
  }

  // a lifecycle machine as a small solar system: its states on a ring (offsets from the planet centre), its transitions as chords
  function planet(name: string, cx: number, cy: number, R: number, primary: boolean, host?: string): Planet {
    const flow = S.flows[name] ?? { name, machine: { states: [], transitions: [] }, agents: [] }, st = flow.machine.states, out: Record<string, MState> = {}, counts: Record<string, number> = {}, agents = hosted(S, name, host);
    agents.forEach((a) => (counts[a.state] = (counts[a.state] || 0) + 1));
    st.forEach((s, i) => {
      const t = (i / st.length) * TAU - Math.PI / 2;
      out[s.id] = { id: s.id, name: s.name, final: s.final, initial: s.initial, machine: name, n: counts[s.id] || 0, loops: loopsOf(flow, s.id), mini: true,
        dx: Math.cos(t) * R, dy: Math.sin(t) * R, x: 0, y: 0, color: RAMP[Math.round((i / st.length) * (RAMP.length - 1))] };
    });
    const p: Planet = { name, R, primary, states: out, edges: flow.machine.transitions.map((t) => ({ ...t, machine: name, a: out[t.source], b: out[t.target] })), n: agents.length, x: 0, y: 0 };
    place(p, cx, cy);
    return p;
  }

  // State level: the state's primary lifecycle machine sits at the centre with the machines its tasks open (skills) around it, joined by
  // paths as the Board joins its states; a state with no machines is a small sun. Each task orbits the machine it is working in, else the
  // primary. The Board transitions into and out of the state run as paths off the left and right edges.
  function buildState(sid: string) {
    const subs = (SUBS[sid] || []).filter((f) => S.flows[f]), bevOf = (id: string) => EVENTS.filter((e) => e.machine === "board" && e.task === id);
    // a task in the state or passing through it is drawn once, and on a terminal state a day's arrival there only when it is neither; a starting
    // state draws none
    const st = board.machine.states.find((s) => s.id === sid), here = st?.initial ? [] : board.agents.filter((a) => (a.state === sid && !stale(S, a)) || bevOf(a.id).some((e) => e.from === sid || e.to === sid));
    const today = S.today[sid] ?? [], list = [...here, ...(st?.final ? today.filter((t) => !here.some((a) => a.id === t.id)) : [])];
    scene.h = subs.length ? 1300 : 820;
    scene.w = Math.max(subs.length ? 1800 : 1000, Math.round((scene.h * W) / H));
    scene.sid = sid;
    const cx0 = scene.w / 2, cy0 = scene.h / 2;
    if (!subs.length) {
      const n = stateCount(S, sid);
      const sun: Sun = { id: sid, name: stateName(sid), final: !!st?.final, today: st && daily(st) ? today.length : undefined, x: cx0, y: cy0, r: SUN_R, R: 0, n, color: BOARD_COLOR[sid] ?? "#94a3b8" };
      scene.sun = sun;
      scene.pivot = sun;
      sun.R = attach(list, sun, sun.r + 30, 16, 16, true);
      sun.rim = sun.R + 8;
      scene.box = [sun.x - sun.R - 120, sun.y - sun.R - 120, sun.x + sun.R + 120, sun.y + sun.R + 120];
    } else {
      // the skill machines are moons: small named bodies the primary's machine opens, held still in rows once their orbits are known
      const allSkills = subs.slice(1), pg = paged(sid, allSkills, ctx.pages?.[sid] ?? 0), skills = pg.shown, pivot = planet(subs[0], cx0, cy0, 104, true, sid);
      const moons = skills.map((name) => Object.assign(planet(name, 0, 0, 9, false, sid), { moon: true }));
      for (const pager of pg.pagers) moons.push({ name: pager.title, label: pager.title, pager, moon: true, primary: false, R: 9, x: 0, y: 0, states: {}, edges: [], chain: [], n: 0 });
      scene.pivot = pivot;
      // a skill machine's sub-states (its states that open a child machine) are small bodies in a chain beside its moon, each opening that machine
      const chains = moons.filter((p) => !p.pager).flatMap((p) => {
        const qs = S.flows[p.name].machine.states.filter((q) => S.child[p.name]?.[q.id]);
        p.chain = qs.map((q) => ({ name: `${p.name}>${q.id}`, title: q.name.replace(/^Pr /, "PR "), machine: p.name, state: q.id, flow: S.child[p.name][q.id].machine, when: S.child[p.name][q.id].when, subState: true,
          primary: false, R: 6, x: 0, y: 0, states: {}, edges: [], n: hosted(S, p.name, sid).filter((a) => a.state === q.id).length }));
        if (p.chain.length) p.label = `${p.name} › ${p.chain.map((b) => b.title).join(" · ")}`;
        return p.chain;
      });
      scene.planets.push(pivot, ...moons, ...chains);
      // a task orbits the deepest body drawn that it is in: the sub-state its latest event left it in, else the moon of the skill machine it works,
      // else the primary. It gets a place on each body it visits in the hour and hops between them as its session moves
      const rawHostAt = (id: string, t: number) => {
        const e = EVENTS.findLast((e) => e.task === id && e.at <= t && subs.includes(e.machine));
        return e && e.machine !== subs[0] && S.child[e.machine]?.[e.to] ? `${e.machine}>${e.to}` : e?.machine || subs[0];
      };
      // a task in a hidden machine orbits the pager node standing in for it
      const shown = (name: string) => pg.pagers.find((pager) => pager.hidden.includes(name.split(">")[0]))?.title ?? name;
      scene.hostAt = (id: string, t: number) => shown(rawHostAt(id, t));
      // on the primary, the trail names the primary's state (`in-progress#pr_opened`), so its moves inside the primary are hops too
      scene.hostTrail = (id: string) =>
        EVENTS.filter((e) => e.task === id && subs.includes(e.machine))
          .map((e) => ({ at: e.at, host: e.machine === subs[0] && pivot.states[e.to] ? `${subs[0]}#${e.to}` : scene.hostAt!(id, e.at) }))
          .filter((r, i, all) => r.host !== all[i - 1]?.host);
      const rawVisits = list.map((a) => {
        const seen = new Set([rawHostAt(a.id, T - HOUR), rawHostAt(a.id, T)]);
        for (const e of EVENTS) if (e.task === a.id && e.at >= T - HOUR && subs.includes(e.machine)) seen.add(rawHostAt(a.id, e.at));
        return seen;
      });
      const byPlanet = new Map<Planet, RawTask[]>(scene.planets.map((p) => [p, []]));
      list.forEach((a, i) => {
        const seen = new Set([...rawVisits[i]].map(shown));
        for (const name of seen) byPlanet.get(scene.planets.find((p) => p.name === name)!)!.push(a);
      });
      // the primary grows, its states with it, until its tasks circle it in one ring
      const grown = oneRing(byPlanet.get(pivot)!.length, 17, 36, pivot.R);
      for (const q of Object.values(pivot.states)) [q.dx, q.dy] = [(q.dx! * grown) / pivot.R, (q.dy! * grown) / pivot.R];
      pivot.R = grown;
      place(pivot, cx0, cy0);
      for (const [p, ts] of byPlanet) {
        const small = p.moon || p.subState, [r0, gap, ringGap, pad] = small ? [p.R + 10, 9, 8, 4] : [p.R + 36, 17, 15, 14];
        p.outer = ts.length ? attach(ts, p, r0, gap, ringGap, true, 4) : p.R + pad;
        p.rim = p.outer + (small ? 3 : 8);
      }
      // the moons alternate right and left of the primary, then upper and lower, and stack in rows from the band beside the primary out to
      // four-fifths of the ring, so the Board paths keep the band and the DAGs keep the space above and below. A row is a line of type or the
      // moon's orbit, whichever is taller (type holds its screen size, so its height is estimated at the fit zoom); the ring grows until every
      // quarter's rows fit
      const shownMoons = moons.filter((p) => !p.pager), band = pivot.rim! + 70, quads = [0, 1].flatMap((sd) => {
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
        for (const [a, b] of [[pivot, q], [q, pivot]]) {
          const dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy), ux = dx / L, uy = dy / L, p0 = { x: a.x + ux * a.rim!, y: a.y + uy * a.rim! }, p1 = { x: b.x - ux * b.rim!, y: b.y - uy * b.rim! };
          const m = Math.hypot(p1.x - p0.x, p1.y - p0.y) * 0.14;
          scene.hops.push({ from: a.name, to: b.name, back: b === pivot, p0, p1, c: { x: (p0.x + p1.x) / 2 - uy * m, y: (p0.y + p1.y) / 2 + ux * m } });
        }
      scene.box = boxOf([
        // every moon is named beside it; a pager node's orbit reaches below the ring
        ...moons.flatMap((p) => [[p.x + (p.x < cx0 ? -1 : 1) * (p.rim! + (p.ext ?? 0) + 30 + (textW(p.label || p.name, 11.5) * lh) / 17), p.y], [p.x, p.y + p.rim!]]),
        [pivot.x - pivot.outer! - 110, pivot.y - pivot.outer! - 50], [pivot.x + pivot.outer! + 110, pivot.y + pivot.outer! + 90],
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
    const kids = S.tree.children[name] ?? [], phases = new Set(kids.map((c) => (kids.find((k) => k.state === c.state && k.machine === c.state) ?? kids.find((k) => k.state === c.state))!.machine));
    const only = ctx.only, ranked = rankRows(S.flows, name, ctx.held).filter((m) => !only || only.machines.includes(m));
    const order = shownRows(ranked, (m) => S.flows[m].last ?? 0, !only && ctx.paging?.top === name ? ctx.paging : null), machines = order.map((m) => ({ name: m, states: S.flows[m].machine.states, transitions: S.flows[m].machine.transitions, tasks: tasksOf(S.flows[m]), nested: nestsOf(S.flows, m), phase: phases.has(m) }));
    const lane = laneRows(machines, { x0: top.x0, x1: top.xEnd }, { scale: ctx.scale ?? 100, laneH: laneBottom - laneTop, total: ranked.length, measure: frame.measure });
    const rows = lane.rows.map((r): RowView => {
      const st = S.flows[r.name].machine.states;
      return { ...r, kind: phases.has(r.name) ? "phase" : kids.some((k) => k.machine === r.name) ? "sub" : undefined, init: (st.find((x) => x.initial) ?? st[0]).id, nodes: r.nodes.map((n) => ({ ...n, color: RAMP[Math.round(n.u * (RAMP.length - 1))] })) };
    });
    const more = ranked.length - rows.length, foot = more ? 34 * fs : 0;
    scene.top = { ...top, machine: name, entered, rows, laneTop, laneBottom, total: ranked.length, ranked, more, foot, task: only?.task, ...laneContent(rows, foot, { h: laneBottom - laneTop, fs }) };
    for (const n of top.nodes) scene.mStates[n.id] = { id: n.id, name: n.name, final: n.final, initial: n.initial, machine: name, n: n.n, x: n.x, y: n.y, loops: loopsOf(flow, n.id), color: RAMP[Math.round(n.u * (RAMP.length - 1))] };
    scene.mEdges = flow.machine.transitions.map((t) => {
      const a = scene.mStates[t.source], b = scene.mStates[t.target];
      return { ...t, machine: name, a, b, bend: a && b && b.x < a.x - 1 ? 0.28 : 0.08 };
    });
    agents.forEach((a) => scene.machineTasks.push({ ...a, machine: name }));
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
    const held0 = led.rows === "merge" ? S.ledgers[led.event] : undefined, merges = held0 ?? [];
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
    f.ledger = { event: led.event, rows: led.rows, loading: led.rows === "merge" && held0 === undefined, mark: { x: writer ? writer.x : (f.p0.x + f.p1.x) / 2, y: yP }, J: { x: sx, y: yH }, bus, cap, cols };
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
 * Lay the Board paths of a state level from the pivot's rim to just past the left
 * and right screen edges at the fit view: entries fan in on the left, exits fan
 * out on the right, ranked the same at both ends so no two cross.
 */
export function edgePaths(scene: Scene, fit: { k: number; x: number }, W: number, stateName: (id: string) => string) {
  const pivot = scene.pivot!, left = -fit.x / fit.k - 60, right = (W - fit.x) / fit.k + 60, gap = 120, F = 1 / fit.k;
  for (const [list, side] of [[scene.entries, -1], [scene.exits, 1]] as const)
    list.forEach((l, i) => {
      const n = list.length, off = i - (n - 1) / 2, a = (side < 0 ? Math.PI : 0) + side * off * 0.2, rim = { x: pivot.x + Math.cos(a) * pivot.rim!, y: pivot.y + Math.sin(a) * pivot.rim! };
      const far = { x: side < 0 ? left : right, y: pivot.y + off * gap }, c = { x: rim.x + side * 420, y: far.y };
      Object.assign(l, side < 0 ? { p0: far, c, p1: rim } : { p0: rim, c, p1: far });
      // the quiet name ("from Ready", "to Review") sits on the path just inside the screen edge
      const name = side < 0 ? `from ${stateName(l.source)}` : `to ${stateName(l.target)}`, inX = (textW(name, 10.5) / 2 + 24) * F;
      const pts = sample(l as BEdge & Curve, 80), q = side < 0 ? pts.find((p) => p.x >= left + 60 + inX) : pts.findLast((p) => p.x <= right - 60 - inX);
      l.lab = { name, x: (q || rim).x, y: (q || rim).y };
    });
}
