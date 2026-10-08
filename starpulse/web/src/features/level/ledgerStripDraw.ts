// Draws the Ledger's 24-hour strip from the approved mockup (starpulse#95, view C): a tick for each quarter-hour of merges, red where a workflow failed,
// a star over each unresolved merge, a ↻ under each forced rerun, and the span of the rows in view tinted, named with how many of the day are loaded.
import { clockHm, type ClockMode } from "../../shared/clock";
import type { Ink } from "./ledgerRows";
import { stripLabel, stripMarks } from "./ledgerStrip";
import type { LedgerView } from "../../render/scene";
import type { LedgerRow, MergeStrip } from "../../api";

const ACT = "#fbbf24", MUTED = "#94a3b8", HOUR = 3600, DAY = 86400;

const rgba = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
};

export interface StripFrame {
  led: LedgerView;
  data: MergeStrip;
  /** Every unresolved merge, not only those the band shows. */
  pins: readonly LedgerRow[];
  /** The merges whose rows are in the viewport. */
  inView: readonly LedgerRow[];
  /** How many of the day's merges the page holds. */
  loaded: number;
  now: number;
  mode: ClockMode;
  px: (n: number) => number;
  palette: Record<string, string>;
}

export function drawStrip(ink: Ink, f: StripFrame): void {
  const s = f.led.grid?.strip;
  if (!s) return;
  const { px, palette } = f, m = stripMarks(f.data, f.pins, f.now, s.x0, s.x1), top = s.y - s.h / 2, bottom = s.y + s.h / 2;
  const total = f.data.buckets.reduce((n, b) => n + b.merges, 0);

  ink.stroke([{ x: s.x0, y: s.y }, { x: s.x1, y: s.y }], rgba(MUTED, 0.18), 1);
  for (let t = Math.ceil((f.now - DAY) / HOUR) * HOUR; t <= f.now; t += HOUR) {
    const x = m.x(t);
    ink.stroke([{ x, y: bottom + px(2) }, { x, y: bottom + px(5) }], rgba(MUTED, 0.3), 1);
    if (Number(clockHm(t, "24").slice(0, 2)) % 3 === 0) ink.text(clockHm(t, f.mode), x, bottom + px(14), px(10), rgba(MUTED, 0.5), "center");
  }
  ink.text(`last 24 h · ${total} merge${total === 1 ? "" : "s"}`, s.x0, top - px(12), px(10.5), rgba(MUTED, 0.7), "left");

  if (f.inView.length) {
    const at = f.inView.map((r) => r.at), a = m.x(Math.min(...at)), b = m.x(Math.max(...at));
    ink.rect({ x0: a - 3, y0: top - 3, x1: b + 3, y1: bottom + 3 }, rgba(ACT, 0.06));
    ink.text(stripLabel(f.inView, f.loaded, total, f.mode), s.x1, top - px(12), px(10), rgba(ACT, 0.6), "right");
  }
  for (const t of m.ticks) ink.stroke([{ x: t.x, y: top }, { x: t.x, y: bottom }], rgba(t.failed ? palette.failed : palette.succeeded, t.failed ? 0.85 : 0.5), 1.2);
  for (const x of m.pins) ink.star4(x, top - px(6), px(4.5), palette.failed);
  for (const r of m.reruns) ink.text("↻", r.x, bottom + px(10), px(11), rgba(ACT, 0.9), "center", 500);
}
