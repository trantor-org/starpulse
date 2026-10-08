// The Ledger's unresolved band from the approved mockup (starpulse#95, view C): a merge whose cued run failed stays pinned above the rows, which scroll
// beneath it, until its cue's `resolves` rule clears the failure. Pure: it says which merges pin, and what is left of the rows' viewport under them.
import type { Scroll, Viewport } from "./ledgerScroll";
import type { LedgerRow } from "./api";

/** What the band holds: the pins it shows, how many more wait among the rows, and how many failed runs every pin carries. */
export interface Pins {
  shown: LedgerRow[];
  all: LedgerRow[];
  below: number;
  failed: number;
}

const openFails = (row: LedgerRow) => Object.values(row.fails).filter((f) => f.resolved === null).length;

/**
 * The pins of `rows` (the merges loaded) and `extra` (the pins the snapshot's head left out), newest first and each merge once. The band shows the
 * newest `cap`; the rest stay among the rows, and `below` counts them.
 */
export function pinsOf(rows: readonly LedgerRow[], extra: readonly LedgerRow[], cap: number): Pins {
  const seen = new Set<string>(), all: LedgerRow[] = [];
  for (const r of [...rows, ...extra]) {
    if (seen.has(r.key)) continue;
    seen.add(r.key);
    if (openFails(r)) all.push(r);
  }
  all.sort((a, b) => b.at - a.at);
  const shown = all.slice(0, cap);
  return { shown, all, below: all.length - shown.length, failed: all.reduce((n, r) => n + openFails(r), 0) };
}

/** The rows' viewport with `n` pins above it: the pins' rows and a gap taken off its top. */
export function portOf(grid: Viewport & { gap: number }, n: number): Viewport {
  const band = n ? n * grid.rh + grid.gap : 0;
  return { top: grid.top + band, view: grid.view - band, rh: grid.rh };
}

/** `sc` scrolling past the merges `pins` shows; the same object when it already does, so a frame that changes nothing allocates nothing. */
export function withPins(sc: Scroll, pins: Pins): Scroll {
  const keys = pins.shown.map((r) => r.key);
  return keys.length === sc.skip.size && keys.every((k) => sc.skip.has(k)) ? sc : { ...sc, skip: new Set(keys) };
}
