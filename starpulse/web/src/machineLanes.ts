// The machine ledger's lane: where each row sits under the top and where its states sit in it. Pure layout; the renderer draws it. A row is as
// tall as its meta column or its machine, whichever is taller, and a lane with few rows stretches them to fill it.
import { hits, layers, slot, sizes, type Block } from "./machineLedger";
import type { MachineState, Transition } from "./types";

export interface LaneMachine {
  name: string;
  states: MachineState[];
  transitions: Transition[];
  /** Tasks on each state. */
  tasks: Record<string, number>;
}
export interface LaneNode {
  id: string;
  name: string;
  /** Across the lane, by depth along the machine. */
  x: number;
  /** Below (positive) or above the row's main line. */
  oy: number;
  r: number;
  /** How far its orbiting tasks reach from its centre. */
  orbit: number;
  /** Where along the machine it sits, 0 at its first state to 1 at its last. */
  u: number;
  initial: boolean;
  final: boolean;
  n: number;
  /** Its name goes above the line (else below), or beside it when its column holds three or more states. */
  up: boolean;
  beside: boolean;
}
export interface LaneRow {
  name: string;
  /** Down from the top of the lane, and the row's height. */
  y: number;
  h: number;
  /** Down from the row's top to its main line. */
  c: number;
  nodes: LaneNode[];
}

/** Rows to a page: a lane holding more does not stretch them. */
export const PAGE = 20;
/** How far a lane of few rows stretches them. */
export const STRETCH = 3.2;

export function laneRows(machines: LaneMachine[], span: { x0: number; x1: number }, f: { scale: number; laneH: number }): { rows: LaneRow[]; k: number } {
  const { fs, gs, dot } = sizes(f.scale), rg = 32 * fs, pad = 26 * fs + 10.5 * fs * 1.3, metaH = 12 * fs * 1.4 + 2 * 10 * fs * 1.5 + 34 * fs;
  const gl = machines.map((m) => layers(m.states, m.transitions.filter((t) => t.source !== t.target)));
  const hOf = (g: (typeof gl)[number]) => Math.max(metaH, 2 * pad + (g.rmax - g.rmin) * rg);
  const total = gl.reduce((a, g) => a + hOf(g), 0), k = machines.length <= PAGE ? Math.max(1, Math.min(STRETCH, (f.laneH * 0.97) / Math.max(1, total))) : 1;
  let y = 0;
  const rows = machines.map((m, i): LaneRow => {
    const g = gl[i], h = hOf(g) * k, n = g.cols.length, r = (8 + 1.2 * Math.sqrt(Math.max(0, ...Object.values(m.tasks)))) * Math.min(2, k) ** 0.6 * gs;
    const nodes = m.states.map((s, j): LaneNode => {
      const c = m.tasks[s.id] ?? 0;
      return {
        id: s.id, name: s.name, x: n > 1 ? span.x0 + (g.depth[s.id] / (n - 1)) * (span.x1 - span.x0) : span.x0, oy: g.row[s.id] * rg * k, r,
        orbit: c ? slot(r, c - 1, f.scale).R + dot : r, u: m.states.length > 1 ? j / (m.states.length - 1) : 0, initial: s.initial, final: s.final, n: c,
        up: g.row[s.id] < 0 || (g.row[s.id] === 0 && g.depth[s.id] % 2 === 1), beside: g.colN[s.id] >= 3,
      };
    });
    const row = { name: m.name, y, h, c: h / 2 - ((g.rmax + g.rmin) / 2) * rg * k, nodes };
    y += h;
    return row;
  });
  return { rows, k };
}

export interface RowLabel {
  id: string;
  text: string;
  /** The label's box, down from the row's top. */
  x: number;
  y: number;
  w: number;
  h: number;
  px: number;
}
/**
 * Names a row's states: above or below the line, alternating, or beside a state in a column of three or more. A name that would touch another, a
 * state's tasks or anything in `keepClear` (a DAG star), or leave its row, is left for the tooltip.
 */
export function rowLabels(row: LaneRow, f: { scale: number; measure: (s: string, px: number) => number; x0: number; x1: number }, keepClear: { x: number; y: number; r: number }[]): RowLabel[] {
  const { fs } = sizes(f.scale), px = 10.5 * fs, h = px * 1.3, out: RowLabel[] = [];
  const placed: (Block | { x: number; y: number; r: number })[] = [...row.nodes.map((n) => ({ x: n.x, y: row.c + n.oy, r: n.orbit + 1 })), ...keepClear];
  for (const n of row.nodes) {
    const w = f.measure(n.name, px), o = n.orbit + 1, ny = row.c + n.oy, xx = Math.max(f.x0 - 24 * fs, Math.min(f.x1 - w, n.x - w / 2));
    const side = [{ x: n.x + o + 8, y: ny - h / 2 }, { x: n.x - o - 8 - w, y: ny - h / 2 }];
    const vert = (n.up ? [true, false] : [false, true]).map((u) => ({ x: xx, y: u ? ny - o - 1.5 - h : ny + o + 1.5 }));
    for (const c of n.beside ? [...side, ...vert] : vert) {
      const b = { x0: c.x - 6, x1: c.x + w + 6, y0: c.y, y1: c.y + h };
      if (b.y0 < 1 || b.y1 > row.h - 1 || b.x0 < f.x0 - 30 * fs || b.x1 > f.x1 + 8 || placed.some((q) => hits(b, q))) continue;
      placed.push(b);
      out.push({ id: n.id, text: n.name, x: c.x, y: c.y, w, h, px });
      break;
    }
  }
  return out;
}

type Pt = { x: number; y: number };
/** A cubic from the state a session leaves to the row's first state. */
export interface Entry {
  p0: Pt;
  c1: Pt;
  c2: Pt;
  p1: Pt;
}
export function entryPath(a: Pt, b: Pt): Entry {
  const dy = b.y - a.y;
  return { p0: a, c1: { x: a.x, y: a.y + dy * 0.6 }, c2: { x: b.x - 30, y: b.y - Math.min(40, Math.abs(dy) * 0.3) * Math.sign(dy || 1) }, p1: b };
}
export function entryAt(e: Entry, t: number): Pt {
  const u = 1 - t;
  return {
    x: u ** 3 * e.p0.x + 3 * u * u * t * e.c1.x + 3 * u * t * t * e.c2.x + t ** 3 * e.p1.x,
    y: u ** 3 * e.p0.y + 3 * u * u * t * e.c1.y + 3 * u * t * t * e.c2.y + t ** 3 * e.p1.y,
  };
}
