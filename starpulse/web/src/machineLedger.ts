// The machine ledger's top: the In Progress machine fixed across the top of its level, in screen pixels. Pure layout: where each
// state sits, how tall the top is and where each state's name goes. The renderer draws it; scene.ts places it on the level.
import type { MachineState, Transition } from "./types";

export interface LedgerMachine {
  states: MachineState[];
  transitions: Transition[];
  /** Tasks on each state. */
  tasks: Record<string, number>;
  /** The states some other machine is entered from. */
  entered: string[];
}
export interface LedgerFrame {
  /** The canvas the level is drawn on, in pixels. */
  W: number;
  H: number;
  /** The page's text size, as a percentage. */
  scale: number;
  /** A string's width in pixels at a font size and weight. */
  measure: (s: string, px: number, weight?: number) => number;
  /** Boxes the page draws over the canvas (its crumb, its clock): no name goes under one. */
  avoid?: { x0: number; y0: number; x1: number; y1: number }[];
  /** How far down the header's own text starts, to clear the page's crumb. */
  inset?: number;
  /** A height the top is at least, so a machine opened from a row stands as tall as the one it was opened from. */
  height?: number;
}
export interface LedgerNode {
  id: string;
  name: string;
  x: number;
  y: number;
  r: number;
  /** How far its orbiting tasks reach from its centre. */
  orbit: number;
  /** Where along the machine it sits, 0 at its first state to 1 at its last. */
  u: number;
  initial: boolean;
  final: boolean;
  n: number;
}
export interface LedgerLabel {
  id: string;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  px: number;
  /** 0 beside or against its node; 1 and 2 are the tiers a crowded name takes further out, on a hairline from its node. */
  tier: number;
  lead: { x: number; y: number } | null;
}
export interface LedgerTop {
  nodes: LedgerNode[];
  labels: LedgerLabel[];
  /** The top's height as drawn, and the height its states need before it is stretched. */
  hdrB: number;
  natural: number;
  /** Where the header's text starts. */
  metaT: number;
  /** The left edge and width of the meta column, and the lane the states run along. */
  metaX: number;
  metaW: number;
  x0: number;
  x1: number;
}

const TAU = Math.PI * 2;
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

/** The sizes a ledger draws at: screen pixels times the page's text size, and dots times its square root so 150% stays on the canvas. */
export const sizes = (scale: number) => {
  const fs = scale / 100, gs = Math.sqrt(fs);
  return { fs, gs, dot: 4 * gs, main: 12.5 * fs };
};

/** Where task `i` of a state of radius `r` orbits: rings of tasks outward from the state, each as full as its circumference holds. */
export function slot(r: number, i: number, scale: number): { R: number; a: number } {
  const { gs } = sizes(scale), sp = 10 * gs;
  let rem = i, R = r + 5.5 * gs;
  for (;;) {
    const cap = Math.max(6, Math.floor((TAU * R) / sp));
    if (rem < cap) return { R, a: (rem / cap) * TAU };
    rem -= cap;
    R += 7.5 * gs;
  }
}
/** A state's radius: one size for every state, so a task arriving or leaving never moves the machine; its orbit shows the load. */
const stateRadius = (scale: number) => 15 * sizes(scale).gs;
/** The room kept round every state for its orbiting tasks, whatever sits on it: two full rings (`slot` puts the first 12 just past the state, the
 * next 17 past that). A state holding more spills a ring past it rather than shift the machine. */
const orbitRoom = (scale: number) => stateRadius(scale) + 13 * sizes(scale).gs + sizes(scale).dot;

export interface Layers {
  depth: Record<string, number>;
  row: Record<string, number>;
  /** States sharing a column with each state, itself included. */
  colN: Record<string, number>;
  cols: string[][];
  rmin: number;
  rmax: number;
}
/** The machine as layers: breadth-first depth from its first state, the longest path to a final state on row 0, the rest alternating above and below it. */
export function layers(states: MachineState[], trans: Transition[]): Layers {
  const ids = states.map((s) => s.id), init = (states.find((s) => s.initial) ?? states[0]).id, depth: Record<string, number> = { [init]: 0 }, par: Record<string, string> = {}, q = [init];
  while (q.length) {
    const s = q.shift()!;
    for (const t of trans) if (t.source === s && !(t.target in depth)) { depth[t.target] = depth[s] + 1; par[t.target] = s; q.push(t.target); }
  }
  let md = Math.max(...Object.values(depth));
  for (const id of ids) if (!(id in depth)) depth[id] = ++md;
  const end = states.filter((s) => s.final && s.id in depth).map((s) => s.id).sort((a, b) => depth[b] - depth[a])[0] ?? ids.reduce((a, b) => (depth[b] > depth[a] ? b : a));
  const main = new Set([init]);
  for (let s: string | undefined = end; s !== undefined; s = par[s]) main.add(s);
  const cols: string[][] = [];
  for (const id of ids) (cols[depth[id]] ??= []).push(id);
  const row: Record<string, number> = {}, colN: Record<string, number> = {};
  for (const col of cols) {
    if (!col) continue;
    const mi = col.find((id) => main.has(id)), rest = col.filter((id) => id !== mi);
    row[mi ?? rest.shift()!] = 0;
    rest.forEach((id, i) => (row[id] = (i % 2 ? 1 : -1) * (Math.floor(i / 2) + 1)));
    for (const id of col) colN[id] = col.length;
  }
  const rows = Object.values(row);
  return { depth, row, colN, cols: cols.filter(Boolean), rmin: Math.min(...rows), rmax: Math.max(...rows) };
}

export interface Block {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
/** A state's tasks keep a disc clear of any name; a name keeps a box clear of the others. */
export const hits = (a: Block, b: Block | { x: number; y: number; r: number }) =>
  "r" in b
    ? Math.hypot(Math.max(a.x0 - b.x, 0, b.x - a.x1), Math.max(a.y0 - b.y, 0, b.y - a.y1)) < b.r
    : a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
type Side = "above" | "below" | "right" | "left";
/** The sides a state's name tries first: beside a column of three or more, away from the main line for a branch, alternating on it. */
const ordOf = (g: Layers, id: string): Side[] =>
  g.colN[id] >= 3 ? ["right", "left", "above", "below"] : g.row[id] < 0 ? ["above", "right", "left", "below"] : g.row[id] > 0 ? ["below", "right", "left", "above"] : g.depth[id] % 2 ? ["above", "below", "right", "left"] : ["below", "above", "right", "left"];

/** Names every state: beside or against it where that is clear, else on a second or third tier on a hairline, the main line named first. */
function placeLabels(nodes: LedgerNode[], g: Layers, f: LedgerFrame, top: { hdrB: number; metaX: number; metaW: number }): LedgerLabel[] {
  const px = sizes(f.scale).main, h = px * 1.3, out: LedgerLabel[] = [], placed: (Block | { x: number; y: number; r: number })[] = [...(f.avoid ?? [])];
  placed.push({ x0: top.metaX - 4, x1: top.metaX + top.metaW, y0: 0, y1: top.hdrB });
  for (const n of nodes) placed.push({ x: n.x, y: n.y, r: n.orbit + 2 });
  const heads = [...nodes].sort((a, b) => Number(g.row[a.id] !== 0) - Number(g.row[b.id] !== 0));
  for (const n of heads) {
    const w = f.measure(n.name, px), rr = n.orbit + 2, xs = [n.x - w / 2, n.x + rr - w, n.x - rr, n.x - w];
    const sides = ordOf(g, n.id).flatMap((sd) =>
      sd === "below" ? xs.map((x) => ({ x, y: n.y + rr + 3 })) : sd === "above" ? xs.map((x) => ({ x, y: n.y - rr - 3 - h })) : sd === "right" ? [{ x: n.x + rr + 10, y: n.y - h / 2 }] : [{ x: n.x - rr - 10 - w, y: n.y - h / 2 }],
    );
    const far = (dir: number, k: number, tier: number) => xs.map((x) => ({ x, y: dir > 0 ? n.y + rr + 3 + h * k : n.y - rr - 3 - h * (k + 1), lead: { x: n.x, y: n.y + dir * rr }, tier }));
    const d = ordOf(g, n.id)[0] === "above" ? -1 : 1;
    const cands = [...sides.map((c) => ({ ...c, lead: null as LedgerLabel["lead"], tier: 0 })), ...[1.1, 2.2].flatMap((k, i) => [...far(d, k, i + 1), ...far(-d, k, i + 1)])];
    for (const c of cands) {
      const r = { x0: c.x, y0: c.y, x1: c.x + w, y1: c.y + h };
      if (r.x0 < 4 || r.x1 > f.W - 4 || r.y0 < 2 || r.y1 > top.hdrB - 2) continue;
      const pad = { x0: r.x0 - 8, x1: r.x1 + 8, y0: r.y0 - 1, y1: r.y1 + 1 };
      if (placed.some((q) => hits(pad, q))) continue;
      placed.push(pad);
      out.push({ id: n.id, text: n.name, x: r.x0, y: r.y0, w, h, px, tier: c.tier, lead: c.lead });
      break;
    }
  }
  return out;
}

export function ledgerTop(m: LedgerMachine, f: LedgerFrame): LedgerTop {
  const { W, H, scale, measure } = f, { fs } = sizes(scale);
  const trans = m.transitions.filter((t) => t.source !== t.target);
  if (!m.states.length) return { nodes: [], labels: [], hdrB: 0, natural: 0, metaT: 0, metaX: 0, metaW: 0, x0: 0, x1: 0 };
  const g = layers(m.states, trans), n = g.cols.length;
  const metaX = 22, metaW = Math.round(clamp(186 * fs, 170, 290)), x0 = metaX + metaW + 34 * fs, x1 = W - 34;
  // nothing here reads the tasks: every state keeps the same radius and the same room for its orbit, so tasks moving through never shift it
  const r = stateRadius(scale), o = orbitRoom(scale), count = (id: string) => m.tasks[id] ?? 0, px = sizes(scale).main;
  // a column of three or more states names them beside it, so the gap after it widens to hold its longest name; the other gaps share what is left,
  // each as far apart as two orbits if there is room, else no closer than two states, and only then does everything shrink to fit
  const low = 2 * o + 10, floor = 2 * r + 10, wide = (c: string[]) => Math.max(...c.map((id) => measure(m.states.find((s) => s.id === id)!.name, px)));
  const need = g.cols.map((c, i) => (c.length >= 3 ? wide(c) + 2 * o + 40 * fs : g.cols[i + 1]?.length >= 3 ? wide(c) / 2 + o + 20 * fs : 0)).slice(0, n - 1);
  const free = need.filter((v) => !v).length, named = need.reduce((a, v) => a + (v ? Math.max(v, low) : 0), 0);
  const u = Math.max(floor, (x1 - x0 - named) / Math.max(1, free));
  const gap = need.map((v) => (v ? Math.max(v, low) : u)), k = (x1 - x0) / Math.max(1, gap.reduce((a, b) => a + b, 0)), xs = [x0];
  gap.forEach((v) => xs.push(xs[xs.length - 1] + v * k));
  // the top is as tall as the machine would be with one row of branches, however wide a branch fans: a wider fan packs its states into that
  // height, never closer than their discs and names allow, and the top grows only when even that does not fit
  const lab = px * 1.3, room = 3.3 * lab + 6, span = g.rmax - g.rmin, base = 10 + 2 * room + 2 * o, ref = Math.min(span, 1);
  const rowGap = Math.max(2 * o + 6, Math.min(Math.max(2 * o + 10, 40 * fs), Math.max(26 * fs, H * 0.4 - 2 * room - 2 * o)));
  const minGap = Math.max(2 * r + 6, lab + 4), one = base + ref * rowGap, packed = base + span * minGap, natural = Math.max(one, packed);
  // half again that height, short of 60% of the view: the branch rows spread apart and the rest pads it above and below
  const hdrB = Math.max(packed, one + clamp(Math.min(0.5 * one, H * 0.6 - one), 0, 0.5 * one), f.height ?? 0);
  const spread = span ? Math.max(minGap, Math.min(2 * rowGap, rowGap + ((hdrB - base - span * rowGap) * 0.6) / span, (hdrB - base) / span)) : rowGap;
  const padT = (hdrB - base - span * spread) / 2, yMain = 10 + padT + room + o - g.rmin * spread;
  // a column of three or more names its states beside it, so it needs no room above or below for names: it spreads over the top's whole
  // height, from under the page's crumb to the hairline, never farther apart than a branch row sits from the main line
  const top = (f.inset ?? 0) + o, bot = hdrB - o;
  const step = g.cols.map((c) => {
    const rs = c.map((id) => g.row[id]), lo = Math.min(...rs), hi = Math.max(...rs);
    return c.length < 3 ? spread : Math.max(spread, Math.min(rowGap, lo < 0 ? (yMain - top) / -lo : Infinity, hi > 0 ? (bot - yMain) / hi : Infinity));
  });
  const nodes = m.states.map((s): LedgerNode => ({
    id: s.id, name: s.name, x: xs[g.depth[s.id]], y: yMain + g.row[s.id] * step[g.depth[s.id]], r, orbit: o, u: n > 1 ? g.depth[s.id] / (n - 1) : 0,
    initial: s.initial, final: s.final, n: count(s.id),
  }));
  return { nodes, labels: placeLabels(nodes, g, f, { hdrB, metaX, metaW }), hdrB, natural, metaT: f.inset ?? 0, metaX, metaW, x0, x1 };
}
