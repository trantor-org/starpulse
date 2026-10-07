// Activity on the orbit card is the real arrivals, aggregated: a comet never stands for one move and never runs on a cycle. A
// source-and-sun pair counts the arrivals it saw, and a comet leaves only when that count crosses the next multiple of the
// quantum, so a quiet pair stays dark and the card moves as much as the work did.
export const DAY = 86400;

/** The replay's seconds for one day of the window at each pace. At `live` a day is a day. */
const PACE_S = { live: DAY, min: 60, fast: 10 } as const;
export type Pace = keyof typeof PACE_S;
export type Measure = "share" | "count" | "flux";

/** Arrivals a comet stands for: 5 under `count`, else a tenth of the source's working runs, never fewer than one. */
export const quantum = (measure: Measure, wip: number) => (measure === "count" ? 5 : Math.max(1, 0.1 * wip));

/** How long a comet is in flight, in animation seconds. */
export const FLIGHT_S = 1.6;
export const paceS = (pace: Pace) => PACE_S[pace];

/** Where in a window of `days` the replay is, after `clock` seconds: looped and started `start` days in, or at `live` the window's end plus the time since. */
export function replayDay(pace: Pace, clock: number, days: number, start: number): number {
  const sec = PACE_S[pace];
  return pace === "live" ? days + clock / sec : (clock / sec + start) % days;
}

const upto = (a: number[], x: number) => {
  let lo = 0, hi = a.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (a[m] <= x) lo = m + 1;
    else hi = m;
  }
  return lo;
};

/** The comets in flight at day `T` over arrivals at `at` (days, oldest first): each one's progress in [0, 1), `span` days being a whole flight. */
export function cometsAt(at: number[], T: number, span: number, q: number): number[] {
  const lo = upto(at, T - span), hi = upto(at, T), out: number[] = [];
  for (let j = Math.floor(lo / q) + 1; j * q <= hi; j++) {
    const u = (T - at[Math.ceil(j * q) - 1]) / span;
    if (u >= 0 && u < 1) out.push(u);
  }
  return out;
}
