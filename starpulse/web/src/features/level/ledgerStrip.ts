// The Ledger's 24-hour strip from the approved mockup (starpulse#95, view C): what its label says of the rows in view, and where its marks fall.
// Pure: it takes the scroll, the server's buckets and the strip's width, and draws nothing.
import { clockHm, type ClockMode } from "../../shared/clock";
import { place, type Scroll, type Viewport } from "./ledgerScroll";
import type { LedgerRow, MergeStrip } from "../../api";

const DAY = 86400;

/** The merges whose rows are in the viewport now, newest first. */
export const inView = (sc: Scroll, vp: Viewport): LedgerRow[] => place(sc, vp).filter((p) => p.y > vp.top && p.y < vp.top + vp.view).map((p) => p.row);

/** `14:25–15:00 in view · 20 of 96 loaded`: the span of the merges in view, and how many of the day's merges the page holds; empty with none in view. */
export function stripLabel(rows: readonly LedgerRow[], loaded: number, total: number, mode: ClockMode): string {
  if (!rows.length) return "";
  const at = rows.map((r) => r.at);
  return `${clockHm(Math.min(...at), mode)}–${clockHm(Math.max(...at), mode)} in view · ${loaded} of ${total} loaded`;
}

/** One quarter-hour of merges on the strip: where it falls, how many merges, and whether a workflow failed on one. */
export interface Tick {
  x: number;
  merges: number;
  failed: boolean;
}

export interface Marks {
  ticks: Tick[];
  /** Forced reruns, at the tick of the quarter-hour they started in. */
  reruns: { x: number; n: number }[];
  /** The pinned merges, each at the minute it landed. */
  pins: number[];
  /** Where a moment falls between `x0` (24 hours ago) and `x1` (now). */
  x: (at: number) => number;
}

/** The marks of `strip` on a strip from `x0` to `x1` ending at `now`; the day sits at the clock, so a strip last sent minutes ago still lines up. */
export function stripMarks(strip: MergeStrip, pins: readonly LedgerRow[], now: number, x0: number, x1: number): Marks {
  const x = (at: number) => x0 + ((at - (now - DAY)) / DAY) * (x1 - x0), inDay = (at: number) => at >= now - DAY && at <= now;
  const ticks: Tick[] = [], reruns: Marks["reruns"] = [];
  strip.buckets.forEach((b, i) => {
    const mid = strip.since + (i + 0.5) * strip.bucket;
    if (!inDay(mid)) return;
    if (b.merges) ticks.push({ x: x(mid), merges: b.merges, failed: b.failed > 0 });
    if (b.reruns) reruns.push({ x: x(mid), n: b.reruns });
  });
  return { ticks, reruns, pins: pins.filter((r) => inDay(r.at)).map((r) => x(r.at)), x };
}
