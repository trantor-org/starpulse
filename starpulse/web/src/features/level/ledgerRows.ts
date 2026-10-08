// Draws a merge Ledger's rows from the approved Ledger mockup (starpulse#95, view C): each merge is a row hung from the spine, its label in the gutter and,
// in every template's column, the run's mini step graph beside its status line. A run paired by time rather than by commit sits in a dashed box,
// amber when another merge landed in its window; another repository's merge sits on the cross lane, linked to the pin-bump row that applies it.
// The rows scroll under the fixed templates (ledgerScroll): only those in the viewport are drawn, clipped to it, with a footer row under the last one
// loaded, a thumb beside them and, once scrolled, a chip back to the newest merge. A merge with an open failure pins above them in the unresolved band,
// which the rows scroll beneath.
// Pure: it draws through the `Ink` the renderer hands it, in the units its scene laid out, and keeps no state.
import { statusLine, type LineCtx } from "./ledger";
import { portOf, type Pins } from "./ledgerPins";
import { PAGE, chip, footer, place, thumbOf, type Scroll } from "./ledgerScroll";
import type { Glyph, LedgerView } from "../../render/scene";
import type { LedgerRow } from "../../api";

export const AMBER = "#f59e0b";
export const CROSS = "#c084fc";
const ACT = "#fbbf24", MUTED = "#94a3b8", INK = "#dbe4f3", BG = "rgba(6,10,20,0.9)";
const NONE: ReadonlySet<string> = new Set();

/** A rectangle in world units. */
export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** Where the pointer can take the Ledger's scrolling, in world units, when it is drawn. */
export interface Hits {
  thumb: Box | null;
  chip: Box | null;
}

/** The canvas marks a row is made of. Sizes of text and radii are world units; stroke weights and dashes are screen pixels. */
export interface Ink {
  text(s: string, x: number, y: number, size: number, col: string, align?: CanvasTextAlign, weight?: number): void;
  /** `s` cut to `max` world units at `size`, ending in an ellipsis when it was cut. */
  fit(s: string, max: number, size: number): string;
  stroke(pts: { x: number; y: number }[], col: string, w?: number, dash?: number[]): void;
  circle(x: number, y: number, r: number, col: string, w?: number): void;
  /** A quarter-turn-and-more of a ring, the loading spinner. */
  arc(x: number, y: number, r: number, from: number, to: number, col: string, w: number): void;
  /** The width of `s` in world units at `size`. */
  width(s: string, size: number, weight?: number): number;
  /** A filled rectangle, with an outline when `line` is given. */
  rect(b: Box, fill: string, line?: string, w?: number): void;
  /** `draw` with everything it paints cut to `b`. */
  clip(b: Box, draw: () => void): void;
  dot(x: number, y: number, r: number, fill: string): void;
  /** A four-pointed star, the mark of a pinned merge. */
  star4(x: number, y: number, r: number, col: string): void;
  /** One expanding ring, `age` from 0 to 1, grown by `grow` screen pixels. */
  pulse(x: number, y: number, r: number, age: number, col: string, grow: number): void;
}

export interface RowsFrame {
  led: LedgerView;
  /** The merges loaded and where the viewport is on them; it scrolls past the merges `pins` shows. */
  scroll: Scroll;
  /** The merges pinned above the rows by an open failure. */
  pins: Pins;
  /** The words for a forced rerun under way, drawn at the band's right; absent with none. */
  rerunning?: string;
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
  /** The key of the row the viewer is on (hovered or open), outlined. */
  lit?: string;
  /** A task's title, when the page holds the task. */
  title?: (task: string) => string | undefined;
}

const rgba = (h: string, a: number) => {
  const n = parseInt(h.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};
const ease = (u: number) => 1 - (1 - u) ** 3;
/** Seconds a new row takes to lower into place, and to fade in at twice the rate. */
const SETTLE = 0.5, RING = 1.2;

export function drawRows(ink: Ink, f: RowsFrame): Hits {
  const { led, px, scroll: sc } = f, g = led.grid, hits: Hits = { thumb: null, chip: null };
  if (!g) return hits;
  const right = led.cols[led.cols.length - 1].x1, J = led.J, ys = new Map<string, number>(), vp = portOf(g, f.pins.shown.length), placed = place(sc, vp);
  const at = (key: string, y: number) => {
    const age = f.age(key);
    return age === undefined ? { y, a: 1, age } : { y: y - (1 - ease(Math.min(1, age / SETTLE))) * g.rh, a: Math.min(1, age / SETTLE), age };
  };
  drawBand(ink, f, at, ys);
  ink.clip({ x0: 0, y0: vp.top, x1: right + px(30), y1: vp.top + vp.view }, () => {
    for (const p of placed) drawRow(ink, f, p.row, at(p.row.key, p.y), ys);
    // another repository's merge, dashed back to the pin-bump merge on the spine that applies it
    for (const p of placed) {
      const to = p.row.appliedBy ? ys.get(p.row.appliedBy) : undefined, y = ys.get(p.row.key);
      if (to === undefined || y === undefined) continue;
      ink.stroke([{ x: g.lane, y }, { x: J.x + px(4), y: to }], rgba(CROSS, 0.6), 1, [2, 3]);
      ink.text("pin bump", (g.lane + J.x) / 2 + px(6), (y + to) / 2, px(9.5), rgba(CROSS, 0.7), "left");
    }
    const foot = footer(sc, vp);
    if (foot && !foot.end) {
      const a0 = f.clock * 5;
      ink.arc(J.x, foot.y, px(5), a0, a0 + 4.2, rgba(ACT, 0.8), px(1.4));
      ink.text(`loading older merges · ${PAGE} at a time`, g.label.x, foot.y, px(11), rgba(MUTED, 0.7), "left");
    } else if (foot) {
      ink.dot(J.x, foot.y, px(2.4), rgba(MUTED, 0.5));
      ink.text(`oldest merge in the last 24 h · ${foot.rows} rows`, g.label.x, foot.y, px(11), rgba(MUTED, 0.55), "left");
    }
  });
  const th = thumbOf(sc, vp, px(24)), x = right + px(14);
  if (th) {
    const hot = sc.drag !== null;
    ink.stroke([{ x, y: vp.top }, { x, y: vp.top + vp.view }], rgba(MUTED, 0.12), 3);
    ink.stroke([{ x, y: vp.top + th.y + px(2) }, { x, y: vp.top + th.y + th.h - px(2) }], rgba(MUTED, hot ? 0.75 : 0.4), 4);
    hits.thumb = { x0: x - px(8), y0: vp.top + th.y, x1: x + px(8), y1: vp.top + th.y + th.h };
  }
  const tip = chip(sc, vp);
  if (tip) {
    const cx = (J.x + right) / 2, cy = Math.min(vp.top + px(14), vp.top + vp.view / 2), w = ink.width(tip, px(11), 500) + px(22), box = { x0: cx - w / 2, y0: cy - px(10), x1: cx + w / 2, y1: cy + px(10) };
    ink.rect(box, "rgba(6,10,20,0.92)", rgba(sc.fresh ? ACT : MUTED, 0.6), 1);
    ink.text(tip, cx, cy, px(11), sc.fresh ? ACT : rgba(INK, 0.85), "center", 500);
    hits.chip = box;
  }
  return hits;
}

/** The unresolved band: a tint and a red edge down the spine behind the pinned rows, drawn above the rows' viewport, its count over them and, at its right, a rerun under way. */
function drawBand(ink: Ink, f: RowsFrame, at: (key: string, y: number) => { y: number; a: number; age: number | undefined }, ys: Map<string, number>) {
  const { led, px, pins } = f, g = led.grid!, red = f.palette.failed ?? "#fb7185", right = led.cols[led.cols.length - 1].x1;
  if (!pins.shown.length) return;
  const y0 = g.top, y1 = g.top + pins.shown.length * g.rh, label = `UNRESOLVED · ${pins.failed} failed run${pins.failed > 1 ? "s" : ""}${pins.below ? ` (+${pins.below} below)` : ""}`;
  ink.rect({ x0: g.label.x, y0, x1: right, y1 }, rgba(red, 0.05));
  ink.stroke([{ x: led.J.x, y: y0 }, { x: led.J.x, y: y1 }], rgba(red, 0.7), 2);
  ink.text(label, g.label.x, y0 - px(9), px(10), rgba(red, 0.9), "left", 500);
  if (f.rerunning) ink.text(f.rerunning, right, y0 - px(9), px(10), ACT, "right", 500);
  pins.shown.forEach((row, i) => drawRow(ink, f, row, at(row.key, y0 + g.rh / 2 + i * g.rh), ys));
}

/** One merge's row at `where`: its hairline, its dot on the spine or the cross lane, its label and every template's cell. */
function drawRow(ink: Ink, f: RowsFrame, row: LedgerRow, where: { y: number; a: number; age: number | undefined }, ys: Map<string, number>) {
  const { led, px } = f, g = led.grid!, { y, a, age } = where, right = led.cols[led.cols.length - 1].x1, J = led.J, cross = row.appliedBy !== undefined;
  ys.set(row.key, y);
  ink.stroke([{ x: J.x, y: y + g.rh / 2 }, { x: right, y: y + g.rh / 2 }], rgba(MUTED, 0.07 * a), 1);
  if (row.key === f.lit) {
    const x0 = Math.min(g.label.x, J.x) - px(6), y0 = y - g.rh / 2, y1 = y + g.rh / 2;
    ink.stroke([{ x: x0, y: y0 }, { x: right, y: y0 }, { x: right, y: y1 }, { x: x0, y: y1 }, { x: x0, y: y0 }], rgba(ACT, 0.5), 1);
  }
  if (cross) {
    ink.dot(g.lane, y, px(3.6), "rgba(6,10,20,1)");
    ink.circle(g.lane, y, px(3.6), rgba(CROSS, 0.9 * a), px(1.3));
    ink.stroke([{ x: J.x, y }, { x: g.lane - px(4), y }], rgba(CROSS, 0.25 * a), 1);
  } else if (row.pinned) ink.star4(J.x, y, px(6.5), f.palette.failed ?? "#fb7185");
  else ink.dot(J.x, y, px(3.4), rgba(ACT, 0.85 * a));
  if (age !== undefined && age < RING * 1.3) ink.pulse(cross ? g.lane : J.x, y, px(3.4), age / RING, ACT, 22);
  // the label: the time and task, the PR and commit after them while there is room, and the task's title under them
  const who = row.tasks[0] ?? (row.applies?.length ? "pin bump" : "—"), sha = (row.sha ?? row.key).slice(0, 7), head = ink.fit(`${f.ctx.hm(row.at)}  ${who}`, g.label.w, px(12.5));
  ink.text(head, g.label.x, y - px(8), px(12.5), rgba(INK, 0.92 * a), "left", 500);
  const used = ink.width(head, px(12.5), 500) + px(8);
  if (used < g.label.w - px(40)) ink.text(ink.fit(row.pr ? `${row.pr.repo} #${row.pr.number} · ${sha}` : sha, g.label.w - used, px(10.5)), g.label.x + used, y - px(8), px(10.5), rgba(MUTED, 0.6 * a), "left");
  const title = row.tasks[0] ? f.title?.(row.tasks[0]) : undefined;
  if (title) ink.text(ink.fit(title, g.label.w, px(11)), g.label.x, y + px(9), px(11), rgba(MUTED, 0.7 * a), "left");
  led.cols.forEach((tie, i) => {
    const cell = g.cells[i], run = row.runs[tie.dag], gl = f.glyphs[tie.dag], line = statusLine(row, tie, run, { ...f.ctx, optional: f.optional[tie.dag] ?? NONE });
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
