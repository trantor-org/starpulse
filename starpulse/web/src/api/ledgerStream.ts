// The rows of one open Ledger, pushed by /api/ledger/<event>/events: the newest page on every connect, then the rows that change.

import type { LedgerRow } from ".";

/** The newest rows of one event's ledger, and whether older ones are left to page. */
export interface LedgerHead {
  rows: LedgerRow[];
  more: boolean;
}

/**
 * One EventSource on /api/ledger/<event>/events, held while that ledger is open: the server sends its newest page first, then the rows
 * that change. `head` gets the page; `rows` gets the changed rows to fold into whatever the page holds. EventSource reconnects by
 * itself, and the first frame of each connection resends the head.
 */
export function openLedger(
  event: string,
  on: { head(page: LedgerHead): void; rows(changed: LedgerRow[]): void },
  open: (url: string) => EventSource = (url) => new EventSource(url),
): { close(): void } {
  const src = open(`/api/ledger/${encodeURIComponent(event)}/events`);
  src.addEventListener("page", (e) => on.head(JSON.parse((e as MessageEvent).data) as LedgerHead));
  src.addEventListener("rows", (e) => on.rows((JSON.parse((e as MessageEvent).data) as { rows: LedgerRow[] }).rows));
  return { close: () => src.close() };
}
