// Asks the server for the next page of an event's older Ledger rows when a merge Ledger's footer row comes into view.
import { apiFetch } from "../../api/apiFetch";
import { type LedgerHead, OCCURRENCES, ledgerRow } from "../../api/ledgerStream";
import { PAGE } from "./ledgerScroll";

/** A page of the `event` rows after the newest `offset`, which the caller holds (a row that reached the head since repeats, and `receive` drops it); null when the server refuses, cannot be reached, holds no ledger for the event or answers something else, so the footer asks again. */
export async function fetchLedger(event: string, offset: number, fetcher: typeof apiFetch = apiFetch): Promise<LedgerHead | null> {
  try {
    const response = await fetcher("/graphql", {
      method: "POST",
      body: JSON.stringify({ query: OCCURRENCES, variables: { event, offset, limit: PAGE } }),
    });
    const body = (await response.json()) as { data?: { occurrences?: { rows?: unknown; more?: boolean } | null }; errors?: unknown[] } | null;
    const page = body?.data?.occurrences;
    return response.ok && !body?.errors?.length && Array.isArray(page?.rows) ? { rows: page.rows.map(ledgerRow), more: page.more === true } : null;
  } catch {
    return null;
  }
}
