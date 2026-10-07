// Asks the server for the next page of older merges when a merge Ledger's footer row comes into view.
import { apiFetch } from "./demo";
import { PAGE } from "./ledgerScroll";
import type { LedgerRow } from "./types";

export interface MergePage {
  merges: LedgerRow[];
  more: boolean;
}

/** The merges older than `before`, a page of them; null when the server refuses, cannot be reached or answers something else, so the footer asks again. */
export async function fetchMerges(before: number, fetcher: typeof apiFetch = apiFetch): Promise<MergePage | null> {
  try {
    const response = await fetcher(`/api/merges?before=${before}&limit=${PAGE}`);
    const body = (await response.json()) as Partial<MergePage> | null;
    return response.ok && Array.isArray(body?.merges) ? { merges: body.merges, more: body.more === true } : null;
  } catch {
    return null;
  }
}
