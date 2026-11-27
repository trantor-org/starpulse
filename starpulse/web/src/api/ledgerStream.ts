// One Ledger's occurrences over POST /graphql: a page query, and the `occurrenceChanges` subscription the open Ledger holds.

import type { LedgerRow, MergeStrip } from ".";
import { apiFetch } from "./apiFetch";
import { retryWait } from "./retry";

/** The newest rows of one event's ledger, and whether older ones are left to page. */
export interface LedgerHead {
  rows: LedgerRow[];
  more: boolean;
}

/** What the merge ledger's pages carry beside its rows: the 24-hour strip and the pins the newest page leaves out. Another event's carry a null strip and no pins. */
export interface LedgerMarks {
  mergeStrip: MergeStrip | null;
  mergePins: LedgerRow[];
}

const ROW = "key at tasks sha pr { repo number url } child appliedBy applies runs fails pinned";
const MARKS = `mergeStrip { since bucket buckets { merges failed reruns } } mergePins { ${ROW} }`;
export const OCCURRENCES = `query($event: String!, $before: Float, $limit: Int) { occurrences(event: $event, before: $before, limit: $limit) { more rows { ${ROW} } } }`;
const OCCURRENCE_CHANGES = `subscription($event: String!) { occurrenceChanges(event: $event) { head more rows { ${ROW} } ${MARKS} } }`;

type Occurrence = Pick<LedgerRow, "key" | "at" | "tasks" | "runs" | "fails" | "pinned"> & {
  sha: string | null;
  pr: LedgerRow["pr"];
  child: boolean;
  appliedBy: string | null;
  applies: string[] | null;
};

/** A row as the page draws it: GraphQL answers a field the row lacks as null, so an unset one is dropped and `appliedBy` stays only on a merge a pin bump applies (null until one has). */
export function ledgerRow({ child, sha, pr, appliedBy, applies, ...row }: Occurrence): LedgerRow {
  return { ...row, ...(sha ? { sha } : {}), ...(pr ? { pr } : {}), ...(child ? { appliedBy } : {}), ...(applies ? { applies } : {}) };
}

/** The `data` of each `next` event in a body, as they complete: `event: next` then `data: {json}`, a blank line ending each; a `: ping` comment is skipped. */
async function* nextEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let held = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    held += decoder.decode(value, { stream: true });
    for (let end = held.indexOf("\n\n"); end >= 0; end = held.indexOf("\n\n")) {
      const lines = held.slice(0, end).split("\n");
      held = held.slice(end + 2);
      if (lines.includes("event: next")) yield JSON.parse(lines.find((l) => l.startsWith("data: "))?.slice(6) ?? "null");
    }
  }
}

interface Change {
  data?: { occurrenceChanges?: { head: boolean; more: boolean; rows: Occurrence[]; mergeStrip: MergeStrip | null; mergePins: Occurrence[] } };
}

/**
 * The subscription for one event's ledger, held while it is open: the server sends its newest page first (`head: true`), then the
 * rows that change. `head` gets the page; `rows` gets the changed rows to fold into whatever the page holds. A dropped connection is
 * reopened after `retryWait`, and its first event resends the head; a 4xx (no such ledger, a refused read) is not retried.
 */
export function openLedger(
  event: string,
  on: { head(page: LedgerHead & LedgerMarks): void; rows(changed: LedgerRow[], marks: LedgerMarks): void },
  fetcher: typeof apiFetch = apiFetch,
): { close(): void } {
  const stop = new AbortController();
  const hold = async (): Promise<boolean> => {
    const response = await fetcher("/graphql", {
      method: "POST",
      body: JSON.stringify({ query: OCCURRENCE_CHANGES, variables: { event } }),
      signal: stop.signal,
    });
    if (response.status >= 400 && response.status < 500) return false;
    if (response.ok && response.body) {
      for await (const next of nextEvents(response.body)) {
        const change = (next as Change | null)?.data?.occurrenceChanges;
        if (!change) continue;
        const rows = change.rows.map(ledgerRow), marks = { mergeStrip: change.mergeStrip, mergePins: change.mergePins.map(ledgerRow) };
        if (change.head) on.head({ rows, more: change.more, ...marks });
        else on.rows(rows, marks);
      }
    }
    return true;
  };
  void (async () => {
    for (let attempt = 0; !stop.signal.aborted; attempt++) {
      try {
        if (!(await hold())) return;
        attempt = 0;
      } catch {
        // a dropped connection reopens below
      }
      await new Promise((resolve) => setTimeout(resolve, retryWait(attempt + 1)));
    }
  })();
  return { close: () => stop.abort() };
}
