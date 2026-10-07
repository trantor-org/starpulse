import { describe, expect, it, vi } from "vitest";
import { fetchMerges } from "./ledgerPage";
import type { LedgerRow } from "./types";

const row = (n: number): LedgerRow => ({ key: `m${n}`, at: 1000 - n, tasks: [], runs: {}, fails: {}, pinned: false });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

describe("fetchMerges", () => {
  it("asks for a page of merges older than the oldest held and returns its rows and whether more remain", async () => {
    const fetcher = vi.fn(() => reply({ merges: [row(1), row(2)], more: true }));

    const page = await fetchMerges(1234, fetcher);

    expect(fetcher).toHaveBeenCalledWith("/api/merges?before=1234&limit=20");
    expect(page).toEqual({ merges: [row(1), row(2)], more: true });
  });

  it("gives null for a refusal, a body that is not a page, and a server that cannot be reached", async () => {
    expect(await fetchMerges(1, () => reply({ error: "no" }, 500))).toBeNull();
    expect(await fetchMerges(1, () => reply({ merges: "nope" }))).toBeNull();
    expect(await fetchMerges(1, () => Promise.reject(new Error("down")))).toBeNull();
  });
});
