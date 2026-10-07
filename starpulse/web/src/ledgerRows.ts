// Draws a merge Ledger's rows from the approved Ledger mockup (starpulse#95, view C): each merge is a row hung from the spine, its label in the gutter and,
// in every template's column, the run's mini step graph beside its status line. A run paired by time rather than by commit sits in a dashed box,
// amber when another merge landed in its window; another repository's merge sits on the cross lane, linked to the pin-bump row that applies it.
// Pure: it draws through the `Ink` the renderer hands it, in the units its scene laid out, and keeps no state.
import { statusLine, type LineCtx } from "./ledger";
import type { Glyph, LedgerView } from "./scene";

export const AMBER = "#f59e0b";
export const CROSS = "#c084fc";
const ACT = "#fbbf24", MUTED = "#94a3b8", INK = "#dbe4f3", BG = "rgba(6,10,20,0.9)";
const NONE: ReadonlySet<string> = new Set();

/** The canvas marks a row is made of. Sizes of text and radii are world units; stroke weights and dashes are screen pixels. */
export interface Ink {
  text(s: string, x: number, y: number, size: number, col: string, align?: CanvasTextAlign, weight?: number): void;
  /** `s` cut to `max` world units at `size`, ending in an ellipsis when it was cut. */
  fit(s: string, max: number, size: number): string;
  stroke(pts: { x: number; y: number }[], col: string, w?: number, dash?: number[]): void;
  circle(x: number, y: number, r: number, col: string, w?: number): void;
  dot(x: number, y: number, r: number, fill: string): void;
  /** One expanding ring, `age` from 0 to 1, grown by `grow` screen pixels. */
  pulse(x: number, y: number, r: number, age: number, col: string, grow: number): void;
}

export interface RowsFrame {
  led: LedgerView;
  /** Each template's step graph, by DAG. */
  glyphs: Record<string, Glyph>;
  ctx: Omit<LineCtx, "optional">;
  /** The steps each DAG applies only sometimes, by DAG. */
  optional: Record<string, ReadonlySet<string>>;
  /** World units of a size in screen pixels. */
  px: (n: number) => number;
  /** Colours by run state, and `waiting`. */
  palette: Record<string, string>;
  /** Animation seconds. */
  clock: number;
  /** Seconds since a row arrived, while it is still arriving. */
  age: (key: string) => number | undefined;
}

const rgba = (h: string, a: number) => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};
const ease = (u: number) => 1 - (1 - u) ** 3;
/** Seconds a new row takes to lower into place, and to fade in at twice the rate. */
const SETTLE = 0.5, RING = 1.2;

export function drawRows(ink: Ink, f: RowsFrame) {
  const { led, px } = f, g = led.grid;
  if (!g) return;
  const right = led.cols[led.cols.length - 1].x1, J = led.J, ys = new Map<string, number>();
  const at = (key: string, y: number) => {
    const age = f.age(key);
    return age === undefined ? { y, a: 1, age } : { y: y - (1 - ease(Math.min(1, age / SETTLE))) * g.rh, a: Math.min(1, age / SETTLE), age };
  };
  for (const r of g.rows) {
    const { y, a, age } = at(r.row.key, r.y), row = r.row;
    ys.set(row.key, y);
    ink.stroke([{ x: J.x, y: y + g.rh / 2 }, { x: right, y: y + g.rh / 2 }], rgba(MUTED, 0.07 * a), 1);
    if (r.cross) {
      ink.dot(g.lane, y, px(3.6), "rgba(6,10,20,1)");
      ink.circle(g.lane, y, px(3.6), rgba(CROSS, 0.9 * a), px(1.3));
      ink.stroke([{ x: J.x, y }, { x: g.lane - px(4), y }], rgba(CROSS, 0.25 * a), 1);
    } else ink.dot(J.x, y, px(3.4), rgba(ACT, 0.85 * a));
    if (age !== undefined && age < RING * 1.3) ink.pulse(r.cross ? g.lane : J.x, y, px(3.4), age / RING, ACT, 22);
    const who = row.tasks[0] ?? (row.applies?.length ? "pin bump" : "—"), sha = (row.sha ?? row.key).slice(0, 7);
    ink.text(ink.fit(`${f.ctx.hm(row.at)}  ${who}`, g.label.w, px(12.5)), g.label.x, y - px(8), px(12.5), rgba(INK, 0.92 * a), "left", 500);
    ink.text(ink.fit(row.pr ? `${row.pr.repo} #${row.pr.number} · ${sha}` : sha, g.label.w, px(10.5)), g.label.x, y + px(9), px(10.5), rgba(MUTED, 0.6 * a), "left");
    led.cols.forEach((tie, i) => {
      const cell = r.cells[i], run = row.runs[tie.dag], gl = f.glyphs[tie.dag], line = statusLine(row, tie, run, { ...f.ctx, optional: f.optional[tie.dag] ?? NONE });
      let tx = tie.x0 + px(14);
      if (run && gl) {
        tx = cell.tx;
        const pos = (n: { x: number; y: number }) => ({ x: cell.gx + n.x * cell.ms, y: y + n.y * cell.ms });
        const stepOf = (name: string) => run.steps[name] ?? (gl.nodes.length === 1 ? run.status : "not_started");
        const color = (name: string) => f.palette[stepOf(name)] ?? MUTED;
        for (const [p, q] of gl.links) ink.stroke([pos(p), pos(q)], rgba(color(q.name), 0.5 * a), 1);
        for (const n of gl.nodes) {
          const c = color(n.name), idle = stepOf(n.name) === "not_started", { x, y: ny } = pos(n);
          ink.dot(x, ny, g.nr, BG);
          ink.circle(x, ny, g.nr, rgba(c, (idle ? 0.45 : 0.85) * a), px(1));
          ink.dot(x, ny, g.nr * 0.34, rgba(c, (idle ? 0.45 : 0.9) * a));
          if (stepOf(n.name) === "running") ink.pulse(x, ny, g.nr, (f.clock * 0.7) % 1, ACT, 10);
        }
        // a run paired by time, not by commit key, sits in a dashed box: amber when a second merge landed before it started
        if (line.mark !== "keyed") {
          const bw = (gl.w * cell.ms) / 2 + g.nr + px(4), bh = Math.max((gl.h * cell.ms) / 2 + g.nr + px(3), px(8)), x = cell.gx;
          ink.stroke([{ x: x - bw, y: y - bh }, { x: x + bw, y: y - bh }, { x: x + bw, y: y + bh }, { x: x - bw, y: y + bh }, { x: x - bw, y: y - bh }], line.mark === "ambiguous" ? rgba(AMBER, 0.8 * a) : rgba(MUTED, 0.45 * a), 1, [2, 3]);
        }
      }
      const room = tie.x1 - tx - px(10), col = line.state ? f.palette[line.state] ?? MUTED : MUTED;
      ink.text(ink.fit(line.main, room, px(11.5)), tx, y - px(7), px(11.5), line.state ? rgba(col, (line.state === "succeeded" ? 0.85 : 1) * a) : rgba(MUTED, 0.7 * a), "left", 500);
      if (line.sub) ink.text(ink.fit(line.sub, room, px(10.5)), tx, y + px(8), px(10.5), line.mark === "ambiguous" ? rgba(AMBER, 0.85 * a) : rgba(MUTED, 0.6 * a), "left");
    });
  }
  // another repository's merge, dashed back to the pin-bump merge on the spine that applies it
  for (const r of g.rows) {
    const to = r.bump ? ys.get(r.bump) : undefined, y = ys.get(r.row.key);
    if (to === undefined || y === undefined) continue;
    ink.stroke([{ x: g.lane, y }, { x: J.x + px(4), y: to }], rgba(CROSS, 0.6), 1, [2, 3]);
    ink.text("pin bump", (g.lane + J.x) / 2 + px(6), (y + to) / 2, px(9.5), rgba(CROSS, 0.7), "left");
  }
}
