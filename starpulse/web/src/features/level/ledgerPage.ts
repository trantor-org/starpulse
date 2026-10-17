// Asks the server for the next page of an event's older Ledger rows when a merge Ledger's footer row comes into view.
import { apiFetch } from "../../api/apiFetch";
import { PAGE } from "./ledgerScroll";
import type { LedgerPage } from "../../api";

/** The `event` rows older than `before`, a page of them; null when the server refuses, cannot be reached or answers something else, so the footer asks again. */
export async function fetchLedger(event: string, before: number, fetcher: typeof apiFetch = apiFetch): Promise<LedgerPage | null> {
  try {
    const response = await fetcher(`/api/ledger/${encodeURIComponent(event)}?before=${before}&limit=${PAGE}`);
    const body = (await response.json()) as Partial<LedgerPage> | null;
    return response.ok && Array.isArray(body?.rows) ? { rows: body.rows, more: body.more === true } : null;
  } catch {
    return null;
  }
}
