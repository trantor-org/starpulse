// A merge Ledger's scroll: the rows run under the fixed templates by wheel, key or thumb, older merges load a page at a time when the footer row comes
// into view, and a merge that lands while the reader is scrolled down counts on a chip instead of moving the rows in view. Pure: every function takes
// the state and returns the next, in the world units the scene laid the viewport out in, and knows nothing of the canvas, the network or the clock.
import type { LedgerRow } from "../../api";

/** Merges the server sends at a time: the snapshot's head, and each page `/api/merges` answers. */
export const PAGE = 20;
/** Seconds before a failed page is asked for again while the footer is still in view. */
const RETRY_S = 5;

/** The rows' viewport under the templates: `view` tall from `top`, `rh` a row. */
export interface Viewport {
  top: number;
  view: number;
  rh: number;
}

export interface Scroll {
  /** The offset drawn, easing to `ty`, the offset asked for. */
  y: number;
  ty: number;
  /** Every merge loaded, newest first. */
  rows: LedgerRow[];
  /** Whether older merges remain on the server. */
  more: boolean;
  fetching: boolean;
  /** Seconds before which a failed page is not asked for again. */
  retryAt: number;
  /** Merges that landed while the reader was scrolled down. */
  fresh: number;
  /** Every key a last look held; null until the first. */
  seen: ReadonlySet<string> | null;
  /** The thumb being dragged: where the pointer took it, and the offset then. */
  drag: { y: number; ty: number } | null;
  /** Keys of rows drawn elsewhere (the unresolved band): the list scrolls without them. */
  skip: ReadonlySet<string>;
}

/** A row's place under the current offset: its index and its centre in world units. */
export interface Placed {
  row: LedgerRow;
  i: number;
  y: number;
}

export const newScroll = (): Scroll => ({ y: 0, ty: 0, rows: [], more: false, fetching: false, retryAt: 0, fresh: 0, seen: null, drag: null, skip: new Set() });

/** The rows the viewport scrolls through: every merge loaded but those drawn elsewhere. */
const list = (sc: Scroll): readonly LedgerRow[] => (sc.skip.size ? sc.rows.filter((r) => !sc.skip.has(r.key)) : sc.rows);

/** The rows, then a footer row, make the content; the offset runs from 0 to what is left past the viewport. */
const maxOf = (sc: Scroll, vp: Viewport) => Math.max(0, (list(sc).length + 1) * vp.rh - vp.view);
const clamp = (v: number, hi: number) => Math.max(0, Math.min(hi, v));
const byTime = (a: LedgerRow, b: LedgerRow) => b.at - a.at;

/** `sc` asked to scroll to `ty`, held between the first row and the footer; back at the newest row, nothing is new. */
function aim(sc: Scroll, vp: Viewport, ty: number): Scroll {
  const to = clamp(ty, maxOf(sc, vp));
  return { ...sc, ty: to, fresh: to < vp.rh / 2 ? 0 : sc.fresh };
}

/** The Ledger's head as a snapshot or a delta last sent it: the newest merges, newer copies of rows already held, and any that just arrived. */
export function take(sc: Scroll, head: readonly LedgerRow[], vp: Viewport): Scroll {
  const have = new Set(head.map((r) => r.key)), first = sc.seen === null;
  const rows = [...head, ...sc.rows.filter((r) => !have.has(r.key))].sort(byTime);
  const arrived = first ? 0 : head.filter((r) => !sc.seen!.has(r.key)).length;
  const next: Scroll = { ...sc, rows, more: first ? head.length >= PAGE : sc.more, seen: new Set(rows.map((r) => r.key)) };
  // a reader scrolled down keeps the rows in view where they are: the offset moves down by what arrived above them
  if (arrived && sc.ty > vp.rh / 2) {
    const by = arrived * vp.rh;
    return { ...next, y: sc.y + by, ty: sc.ty + by, fresh: sc.fresh + arrived };
  }
  return aim(next, vp, sc.ty);
}

/** A wheel turn: pixels by the canvas's zoom, a line a third of a row, a page the viewport. */
export function wheelScroll(sc: Scroll, vp: Viewport, e: { deltaY: number; deltaMode: number }, k: number): Scroll {
  const by = e.deltaMode === 1 ? (e.deltaY * vp.rh) / 3 : e.deltaMode === 2 ? e.deltaY * vp.view : e.deltaY / k;
  return aim(sc, vp, sc.ty + by);
}

/** PgUp, PgDn, Home, End and the arrows; null for any other key. */
export function keyScroll(sc: Scroll, vp: Viewport, key: string): Scroll | null {
  const to: Record<string, number> = {
    PageDown: sc.ty + vp.view * 0.9, PageUp: sc.ty - vp.view * 0.9, ArrowDown: sc.ty + vp.rh, ArrowUp: sc.ty - vp.rh, Home: 0, End: maxOf(sc, vp),
  };
  return key in to ? aim(sc, vp, to[key]) : null;
}

/** The thumb on the track beside the viewport: its offset from the top, its length no shorter than `min`, and how far it can travel; null when every row fits. */
export function thumbOf(sc: Scroll, vp: Viewport, min: number): { y: number; h: number; track: number } | null {
  const max = maxOf(sc, vp);
  if (max <= 0) return null;
  const h = Math.max(min, (vp.view * vp.view) / (vp.view + max));
  return { y: (clamp(sc.y, max) / max) * (vp.view - h), h, track: vp.view - h };
}

/** The pointer took the thumb at screen height `clientY`. */
export const dragStart = (sc: Scroll, clientY: number): Scroll => ({ ...sc, drag: { y: clientY, ty: sc.ty } });

/** The pointer moved to `clientY` with the thumb held: the rows follow it at once, `k` screen pixels to a world unit. */
export function dragMove(sc: Scroll, vp: Viewport, clientY: number, k: number, min: number): Scroll {
  const t = thumbOf(sc, vp, min);
  if (!sc.drag || !t) return sc;
  const next = aim(sc, vp, sc.drag.ty + ((clientY - sc.drag.y) / k) * (maxOf(sc, vp) / t.track));
  return { ...next, y: next.ty };
}

/** `dt` seconds of the drawn offset easing toward the one asked for. */
export function ease(sc: Scroll, dt: number): Scroll {
  const y = sc.y + (sc.ty - sc.y) * Math.min(1, dt * 14);
  return { ...sc, y: Math.abs(sc.ty - y) < 0.5 ? sc.ty : y };
}

/** The rows to draw: those crossing the viewport and one past each edge, where the clip cuts them. */
export function place(sc: Scroll, vp: Viewport): Placed[] {
  const rows = list(sc), from = Math.max(0, Math.floor(sc.y / vp.rh) - 1), to = Math.min(rows.length, Math.ceil((sc.y + vp.view) / vp.rh) + 1);
  return rows.slice(from, to).map((row, k) => ({ row, i: from + k, y: vp.top + vp.rh / 2 + (from + k) * vp.rh - sc.y }));
}

/** Whether to ask for the next page now: older merges remain, none is on its way, and the footer row is in view. */
export const wantsPage = (sc: Scroll, vp: Viewport, now: number): boolean =>
  sc.more && !sc.fetching && now >= sc.retryAt && list(sc).length * vp.rh < sc.y + vp.view;

export const begin = (sc: Scroll): Scroll => ({ ...sc, fetching: true });

/** An older page arrived: its rows join those held, once each, and `more` says whether others remain. */
export function receive(sc: Scroll, merges: readonly LedgerRow[], more: boolean): Scroll {
  const have = new Set(sc.rows.map((r) => r.key)), rows = [...sc.rows, ...merges.filter((r) => !have.has(r.key))].sort(byTime);
  return { ...sc, rows, more, fetching: false, retryAt: 0, seen: new Set(rows.map((r) => r.key)) };
}

/** The page could not be had: the footer waits a while before asking again. */
export const fail = (sc: Scroll, now: number): Scroll => ({ ...sc, fetching: false, retryAt: now + RETRY_S });

/** The row under the last one loaded, while it is in view: `loading` older merges, or the `end` of the day, with the rows held. */
export function footer(sc: Scroll, vp: Viewport): { y: number; end: boolean; rows: number } | null {
  const rows = list(sc).length, y = vp.top + rows * vp.rh - sc.y + vp.rh / 2;
  return y - vp.rh / 2 < vp.top + vp.view && y + vp.rh / 2 > vp.top ? { y, end: !sc.more, rows } : null;
}

/** The chip over a scrolled Ledger: how many merges landed since, else the way back to the newest; none at the top. */
export function chip(sc: Scroll, vp: Viewport): string | null {
  if (sc.y <= vp.rh) return null;
  return sc.fresh ? `↑ ${sc.fresh} new merge${sc.fresh > 1 ? "s" : ""}` : "↑ back to newest";
}

/** Scroll a loaded merge to the middle of the view, unless it is in view already. */
export function scrollToKey(sc: Scroll, vp: Viewport, key: string): Scroll {
  const i = list(sc).findIndex((r) => r.key === key);
  if (i < 0) return sc;
  const top = i * vp.rh;
  return top < sc.ty || top + vp.rh > sc.ty + vp.view ? aim(sc, vp, top - vp.view / 2 + vp.rh / 2) : sc;
}
