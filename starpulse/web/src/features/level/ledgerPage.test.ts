import { describe, expect, it, vi } from "vitest";
import { fetchLedger } from "./ledgerPage";
import type { LedgerRow } from "../../api";

const row = (n: number): LedgerRow => ({ key: `m${n}`, at: 1000 - n, tasks: [], runs: {}, fails: {}, pinned: false });
const occurrence = (n: number) => ({ ...row(n), sha: null, pr: null, child: false, appliedBy: null, applies: null });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));
const answer = (occurrences: unknown) => reply({ data: { occurrences } });

describe("fetchLedger", () => {
  it("asks for the page of one event's rows past those held and returns its rows and whether more remain", async () => {
    const fetcher = vi.fn((_url: string, _init?: RequestInit) => answer({ rows: [occurrence(1), occurrence(2)], more: true }));

    const page = await fetchLedger("MERGED", 40, fetcher);

    const sent = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
    expect(fetcher.mock.calls[0][0]).toBe("/graphql");
    expect(sent.variables).toEqual({ event: "MERGED", offset: 40, limit: 20 });
    expect(page).toEqual({ rows: [row(1), row(2)], more: true });
  });

  it("keeps a pin bump's appliedBy, null until applied, and drops what a row lacks", async () => {
    const child = { ...occurrence(1), child: true, applies: ["x"], sha: "abc" };

    const page = await fetchLedger("MERGED", 1, () => answer({ rows: [child], more: false }));

    expect(page?.rows).toEqual([{ ...row(1), appliedBy: null, applies: ["x"], sha: "abc" }]);
  });

  it("gives null for a refusal, an error, no ledger, a body that is not a page, and a server that cannot be reached", async () => {
    expect(await fetchLedger("MERGED", 1, () => reply({ error: "no" }, 500))).toBeNull();
    expect(await fetchLedger("MERGED", 1, () => reply({ data: { occurrences: null }, errors: [{ message: "bad limit" }] }))).toBeNull();
    expect(await fetchLedger("MERGED", 1, () => answer(null))).toBeNull();
    expect(await fetchLedger("MERGED", 1, () => answer({ rows: "nope" }))).toBeNull();
    expect(await fetchLedger("MERGED", 1, () => Promise.reject(new Error("down")))).toBeNull();
  });
});
