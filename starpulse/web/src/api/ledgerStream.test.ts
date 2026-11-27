import { describe, expect, it, vi } from "vitest";
import { openLedger } from "./ledgerStream";
import type { LedgerRow } from ".";

describe("openLedger", () => {
  const row = (key: string, at: number): LedgerRow => ({ key, at, tasks: [key], runs: {}, fails: {}, pinned: false });
  const occurrence = (r: LedgerRow) => ({ ...r, sha: null, pr: null, child: false, appliedBy: null, applies: null });
  const frame = (change: object) => `event: next\ndata: ${JSON.stringify({ data: { occurrenceChanges: change } })}\n\n`;
  const body = (...chunks: string[]) => new Response(new ReadableStream({ start: (c) => { for (const k of chunks) c.enqueue(new TextEncoder().encode(k)); c.close(); } }));

  it("posts the one event's subscription, hands over its head, then each changed row batch, across split chunks and pings", async () => {
    const heads: unknown[] = [];
    const changed: LedgerRow[][] = [];
    const sent: RequestInit[] = [];
    const strip = { since: 0, bucket: 3600, buckets: [{ merges: 1, failed: 0, reruns: 0 }] };
    const marks = { mergeStrip: strip, mergePins: [occurrence(row("p", 1))] };
    const head = frame({ head: true, more: true, rows: [occurrence(row("a", 2))], ...marks });
    const fetcher = vi.fn(async (_url: string, init?: RequestInit) => {
      sent.push(init ?? {});
      return body(": ping\n\n", head.slice(0, 20), head.slice(20), frame({ head: false, more: false, rows: [occurrence(row("b", 3))], mergeStrip: null, mergePins: [] }));
    });
    const done = new Promise<void>((resolve) => {
      const { close } = openLedger("MERGED", { head: (page) => heads.push(page), rows: (rows, m) => { changed.push(rows); expect(m).toEqual({ mergeStrip: null, mergePins: [] }); close(); resolve(); } }, fetcher);
    });

    await done;

    expect(fetcher.mock.calls[0][0]).toBe("/graphql");
    expect(JSON.parse(String(sent[0].body)).variables).toEqual({ event: "MERGED" });
    expect(heads).toEqual([{ rows: [row("a", 2)], more: true, mergeStrip: strip, mergePins: [row("p", 1)] }]);
    expect(changed).toEqual([[row("b", 3)]]);
  });

  it("does not reopen after a 4xx, and aborts its request when closed", async () => {
    const refused = vi.fn(async () => new Response("{}", { status: 404 }));
    openLedger("NONE", { head: () => {}, rows: () => {} }, refused);
    await vi.waitFor(() => expect(refused).toHaveBeenCalledTimes(1));

    let signal: AbortSignal | undefined;
    const open = vi.fn((_url: string, init?: RequestInit) => { signal = init?.signal ?? undefined; return new Promise<Response>(() => {}); });
    const { close } = openLedger("MERGED", { head: () => {}, rows: () => {} }, open);
    await vi.waitFor(() => expect(open).toHaveBeenCalledTimes(1));
    close();

    expect(signal?.aborted).toBe(true);
    expect(refused).toHaveBeenCalledTimes(1);
  });
});
