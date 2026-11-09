// The machine ledger's pages: which of the machines entered from the open one are loaded, 20 at a time, newest activity first. The snapshot names
// the first page and /api/machines the rest; what is loaded is every machine whose activity is no older than the oldest one held, so a machine
// that is newer than the page shows at once and no machine appears twice, however two pages overlap.
import { PAGE } from "./machineLanes";

export interface Paging {
  /** The machine whose entered machines these are. */
  top: string;
  /** The oldest activity held; every machine at least this recent is loaded. */
  boundary: number;
  /** Older machines remain on the server. */
  more: boolean;
  /** A request is out. */
  busy: boolean;
  /** When the last request failed (seconds), until the next one is sent. */
  failedAt: number | null;
}
export interface PageOf {
  open: string | null;
  machines: readonly string[];
  more: boolean;
}

/** Seconds before a failed request is sent again. */
export const RETRY = 5;

/** The first page, as the snapshot names it. */
export function paging(page: PageOf, lastOf: (name: string) => number): Paging {
  return { top: page.open ?? "", boundary: Math.min(Infinity, ...page.machines.map(lastOf)), more: page.more, busy: false, failedAt: null };
}

/** `rows` (ranked, newest first) cut to what is loaded; with no page, or none remaining, every one. */
export function shownRows(rows: readonly string[], lastOf: (name: string) => number, p: Paging | null): string[] {
  return p?.more ? rows.filter((n) => lastOf(n) >= p.boundary) : [...rows];
}

/** The footer in view asks for the next page, once, and again a few seconds after a failure. */
export function wantNext(p: Paging | null, footerInView: boolean, now: number): boolean {
  return !!p && p.more && footerInView && !p.busy && (p.failedAt === null || now - p.failedAt >= RETRY);
}

export const asked = (p: Paging): Paging => ({ ...p, busy: true });
export const failed = (p: Paging, now: number): Paging => ({ ...p, busy: false, failedAt: now });

/** The route that returns the machines entered from the open one older than the oldest held. */
export const nextQuery = (p: Paging): string => `/api/machines?open=${encodeURIComponent(p.top)}&before=${p.boundary}&limit=${PAGE}`;

/** A page arrived: its machines and their activity (null for none, which sorts last). */
export function arrived(p: Paging, machines: readonly { name: string; last: number | null }[], more: boolean): Paging {
  return { ...p, boundary: Math.min(p.boundary, ...machines.map((m) => m.last ?? 0)), more, busy: false, failedAt: null };
}

/** A row older than the oldest held is brought in with every row between: the snapshot already holds them, so nothing is fetched. */
export const reveal = (p: Paging, rowLast: number): Paging => (rowLast >= p.boundary ? p : { ...p, boundary: rowLast });
