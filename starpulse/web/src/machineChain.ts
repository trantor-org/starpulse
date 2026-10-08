// The band under a machine ledger row that shows where its nesting is. Every machine entered from the row's machine is a block under the column
// of the state it is entered from, side by side, top state's first; each state runs a solid stem out of its left, down and along a bus to its
// blocks, the top state's outermost and lowest so no two cross. A block is its machine's states as a line of dots, each deeper machine on its own
// line hung from the state it is entered from (four lines at most, then `+N deeper`), then its name; names that would not fit their block
// alternate between two baselines. Pure layout, down from the row's top; the renderer draws it.
import { layers, sizes, type Block, type Layers } from "./machineLedger";
import type { FlowSnapshot } from "./types";

/** A machine entered from another: its states along its machine, and the machines entered from each. */
export interface Nest {
  name: string;
  states: string[];
  kids: { state: string; nest: Nest }[];
}
type Pt = { x: number; y: number };
/** One machine's states as a line of dots; `a` is its share of the block's ink, fainter each level down. */
export interface ChainLine {
  machine: string;
  states: string[];
  x: number;
  y: number;
  dx: number;
  r: number;
  a: number;
}
export interface ChainBlock {
  name: string;
  lines: ChainLine[];
  /** The dashed drop from a state to the machine entered from it, on the line below. */
  hangs: { x: number; y0: number; y1: number; a: number }[];
  /** Where its name starts (`y` its middle) and how wide it may run, `tail` the deeper machines not drawn. */
  label: { x: number; y: number; w: number };
  tail: string;
}
export interface ChainCol {
  /** The column's room across the row, which it clips to. */
  clip: { x0: number; x1: number };
  stems: { state: string; pts: Pt[]; drops: { x: number; y0: number; y1: number }[] }[];
  blocks: ChainBlock[];
}
export interface Chain {
  cols: ChainCol[];
  /** What the row's state names keep off: each stem's run down, and each column's band. */
  keep: Block[];
}
type Kid = { state: string; nest: Nest };
interface Frame {
  scale: number;
  measure: (s: string, px: number) => number;
  /** The lane's right edge: the last column's room runs a little past it. */
  x1: number;
}

/** The machines entered from `name`, each with the state it is entered from, its states in order along its machine and its own nested machines. */
export function nestsOf(flows: Record<string, FlowSnapshot>, name: string, seen: ReadonlySet<string> = new Set([name])): Kid[] {
  return Object.values(flows)
    .filter((f) => f.parent === name && f.name !== name && !seen.has(f.name) && f.ties?.[0]?.machine === name && f.ties[0].state)
    .sort((a, b) => (a.name < b.name ? -1 : 1))
    .map((f) => {
      const g = layers(f.machine.states, f.machine.transitions.filter((t) => t.source !== t.target)), ids = f.machine.states.map((s) => s.id);
      const states = ids.slice().sort((a, b) => g.depth[a] - g.depth[b] || g.row[a] - g.row[b]);
      return { state: f.ties![0].state!, nest: { name: f.name, states, kids: nestsOf(flows, f.name, new Set([...seen, f.name])) } };
    });
}

const desc = (n: Nest): number => n.kids.reduce((a, k) => a + 1 + desc(k.nest), 0);
const linesOf = (n: Nest) => Math.min(4, 1 + desc(n));
/** The machines entered from a row's states by the column of the state, top state first. */
function columns(kids: Kid[], g: Layers): Map<number, Kid[]> {
  const cols = new Map<number, Kid[]>();
  for (const k of kids) if (k.state in g.depth) (cols.get(g.depth[k.state]) ?? cols.set(g.depth[k.state], []).get(g.depth[k.state])!).push(k);
  for (const es of cols.values()) es.sort((a, b) => g.row[a.state] - g.row[b.state] || (a.nest.name < b.nest.name ? -1 : 1));
  return new Map([...cols].sort((a, b) => a[0] - b[0]));
}
/** A column's room, from its first state to the next column's, the width of each block, and whether its names alternate between baselines to fit. */
function room(cols: Map<number, Kid[]>, d: number, xOf: (s: string) => number, f: Frame) {
  const es = cols.get(d)!, ds = [...cols.keys()], nx = ds[ds.indexOf(d) + 1], x0 = xOf(es[0].state), sp = 10 * sizes(f.scale).fs;
  const lim = (nx === undefined ? f.x1 + 22 : xOf(cols.get(nx)![0].state)) - 14, bw = (lim - x0 + 4) / es.length;
  return { x0, lim, bw, two: es.length > 1 && es.some((e) => f.measure(e.nest.name, sp) > bw - 12) };
}
const stateCount = (es: Kid[]) => new Set(es.map((e) => e.state)).size;

/** How much taller the row grows: its tallest column's deepest block, a stem's turn per state, and a second name line when names alternate. */
export function chainBand(kids: Kid[], g: Layers, xOf: (s: string) => number, f: Frame): number {
  const cols = columns(kids, g);
  if (!cols.size) return 0;
  const { fs, gs } = sizes(f.scale), sp = 10 * fs, h = (n: Nest) => linesOf(n) * 8 * gs + sp * 1.4 + 6;
  return Math.max(...[...cols].map(([d, es]) => stateCount(es) * 5 + Math.max(...es.map((e) => h(e.nest))) + (room(cols, d, xOf, f).two ? sp * 1.3 : 0))) + 8;
}

/** The band's drawing, for a row whose line and band start `top` down from its top; `at` is where a state sits and how far its tasks reach. */
export function chainOf(kids: Kid[], g: Layers, at: (s: string) => { x: number; y: number; orbit: number }, top: number, rowH: number, f: Frame): Chain | null {
  const cols = columns(kids, g);
  if (!cols.size) return null;
  const { fs, gs } = sizes(f.scale), sp = 10 * fs, step = 8 * gs, rr = 2.4 * gs, out: Chain = { cols: [], keep: [] };
  const ext = (n: Nest, k: number): number => Math.max(n.states.length - 1, ...n.kids.map((c) => n.states.indexOf(c.state) + k * ext(c.nest, k)));
  for (const [d, es] of cols) {
    const sts = [...new Set(es.map((e) => e.state))], K = sts.length, { x0: nx0, lim, bw, two } = room(cols, d, (s) => at(s).x, f);
    const oM = Math.max(...sts.map((q) => at(q).orbit)), bt = top + 4 + K * 5, Lm = Math.max(...es.map((e) => linesOf(e.nest)));
    const xb = (i: number) => nx0 - 2 + i * bw, xv = (k: number) => nx0 - oM - 6 - (K - 1 - k) * 7;
    const col: ChainCol = { clip: { x0: xv(0) - 4, x1: lim }, stems: [], blocks: [] };
    sts.forEach((q, k) => {
      const n = at(q), hy = bt - 2 - k * 5, mine = es.flatMap((e, i) => (e.state === q ? [i] : []));
      col.stems.push({ state: q, pts: [{ x: n.x - n.orbit - 1, y: n.y }, { x: xv(k), y: n.y }, { x: xv(k), y: hy }, { x: xb(mine.at(-1)!) + 2, y: hy }], drops: mine.map((i) => ({ x: xb(i) + 2, y0: hy, y1: bt + step - rr - 1 })) });
      out.keep.push({ x0: xv(k) - 1, x1: xv(k) + 1, y0: n.y, y1: hy });
    });
    es.forEach((e, i) => {
      const x0 = xb(i) + 2, w = bw - 12, dn = desc(e.nest), Lv = linesOf(e.nest), b: ChainBlock = { name: e.nest.name, lines: [], hangs: [], label: { x: 0, y: 0, w: 0 }, tail: "" };
      let lv = 0;
      const rec = (n: Nest, x: number, dx: number, r: number, a: number) => {
        const y = bt + ++lv * step;
        b.lines.push({ machine: n.name, states: n.states, x, y, dx, r, a });
        for (const c of n.kids) {
          if (lv >= Lv) return;
          const xi = x + n.states.indexOf(c.state) * dx;
          b.hangs.push({ x: xi, y0: y + r, y1: bt + (lv + 1) * step - r * 0.85, a: a * 0.6 });
          rec(c.nest, xi, dx * 0.85, r * 0.85, a * 0.8);
        }
      };
      rec(e.nest, x0, Math.min(12 * gs, (w - 4) / Math.max(1, ext(e.nest, 0.85))), rr, 1);
      b.tail = dn > Lv - 1 ? ` +${dn - Lv + 1} deeper` : "";
      b.label = { x: x0 - 2, y: bt + Lm * step + sp * (two && i % 2 ? 2.25 : 0.95), w: two ? Math.min(2 * bw, lim - x0) - 12 : w };
      col.blocks.push(b);
    });
    out.cols.push(col);
    out.keep.push({ x0: xv(0) - 2, x1: lim, y0: bt - K * 5 - 2, y1: rowH });
  }
  return out;
}
