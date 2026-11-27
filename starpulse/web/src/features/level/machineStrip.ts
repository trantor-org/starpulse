// The machine ledger's 24 h strip: the last day, and the stretch of it the rows in view cover. Pure: the renderer draws it.

/** The span the strip covers, in seconds. */
export const WINDOW = 86400;

export interface StripScale {
  t0: number;
  t1: number;
  x: (t: number) => number;
}
/** The strip from `x0` to `x1` ending at `now`: the oldest moment at its left end. */
export function stripScale(x0: number, x1: number, now: number): StripScale {
  return { t0: now - WINDOW, t1: now, x: (t) => x0 + ((t - (now - WINDOW)) / WINDOW) * (x1 - x0) };
}

/** The stretch the rows in view cover, by their last activity within the window; null when none was active in it. */
export function viewSpan(lasts: readonly (number | null)[], t0: number): { from: number; to: number } | null {
  const inside = lasts.filter((t): t is number => t !== null && t > t0);
  return inside.length ? { from: Math.min(...inside), to: Math.max(...inside) } : null;
}

/** The strip's caption: the span in view, then how many of the machines are loaded. */
export function stripLabel(span: { from: number; to: number } | null, loaded: number, total: number, hm: (s: number) => string): string {
  return `${span ? `${hm(span.from)}–${hm(span.to)} in view · ` : ""}${loaded} of ${total} loaded`;
}
