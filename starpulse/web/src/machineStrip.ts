// The machine ledger's 24 h strip: a tick per machine entry across the last day, and the stretch of it the rows in view cover. Pure: the renderer
// draws the ticks in the colour of the state each was entered from (amber for a DAG launch).
import type { MachineEntry } from "./api";

/** The span the strip covers, in seconds. */
export const WINDOW = 86400;
/** How near the pointer must be to a tick (pixels) to be on it. */
const REACH = 4;

export interface StripScale {
  t0: number;
  t1: number;
  x: (t: number) => number;
}
export interface Tick {
  x: number;
  entry: MachineEntry;
}

/** The strip from `x0` to `x1` ending at `now`: the oldest moment at its left end. */
export function stripScale(x0: number, x1: number, now: number): StripScale {
  return { t0: now - WINDOW, t1: now, x: (t) => x0 + ((t - (now - WINDOW)) / WINDOW) * (x1 - x0) };
}

/** A tick for each entry within the window that lands on one of `rows`, oldest first as the server sends them. */
export function ticks(entries: readonly MachineEntry[], rows: readonly string[], scale: StripScale): Tick[] {
  return entries.filter((e) => e.at >= scale.t0 && e.at <= scale.t1 && rows.includes(e.row)).map((entry) => ({ x: scale.x(entry.at), entry }));
}

/** The stretch the rows in view cover, by their last activity within the window; null when none was active in it. */
export function viewSpan(lasts: readonly (number | null)[], t0: number): { from: number; to: number } | null {
  const inside = lasts.filter((t): t is number => t !== null && t > t0);
  return inside.length ? { from: Math.min(...inside), to: Math.max(...inside) } : null;
}

/** The tick nearest `x`, if one is within reach. */
export function tickAt(found: readonly Tick[], x: number): Tick | null {
  let best: Tick | null = null;
  for (const t of found) if (Math.abs(t.x - x) < REACH && (!best || Math.abs(t.x - x) < Math.abs(best.x - x))) best = t;
  return best;
}

/** The strip's caption: the span in view, then how many of the machines are loaded. */
export function stripLabel(span: { from: number; to: number } | null, loaded: number, total: number, hm: (s: number) => string): string {
  return `${span ? `${hm(span.from)}–${hm(span.to)} in view · ` : ""}${loaded} of ${total} loaded`;
}
