import { describe, expect, it, vi } from "vitest";
import { fetchLedger } from "./ledgerPage";
import type { LedgerRow } from "../../api";

const row = (n: number): LedgerRow => ({ key: `m${n}`, at: 1000 - n, tasks: [], runs: {}, fails: {}, pinned: false });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("fetchLedger", () => {
  it("asks for a page of one event's rows older than the oldest held and returns its rows and whether more remain", async () => {
    const fetcher = vi.fn(() => reply({ rows: [row(1), row(2)], more: true }));

    const page = await fetchLedger("MERGED", 1234, fetcher);

    expect(fetcher).toHaveBeenCalledWith("/api/ledger/MERGED?before=1234&limit=20");
    expect(page).toEqual({ rows: [row(1), row(2)], more: true });
  });

  it("gives null for a refusal, a body that is not a page, and a server that cannot be reached", async () => {
    expect(await fetchLedger("MERGED", 1, () => reply({ error: "no" }, 500))).toBeNull();
    expect(await fetchLedger("MERGED", 1, () => reply({ rows: "nope" }))).toBeNull();
    expect(await fetchLedger("MERGED", 1, () => Promise.reject(new Error("down")))).toBeNull();
  });
});
