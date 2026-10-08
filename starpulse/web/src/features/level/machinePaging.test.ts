import { describe, expect, it } from "vitest";
import { arrived, asked, failed, nextQuery, paging, reveal, shownRows, wantNext } from "./machinePaging";

/** Thirty machines m29 (newest) down to m0 (oldest), last active at 1000 + n. */
const all = Array.from({ length: 30 }, (_, i) => `m${29 - i}`);
const last = (n: string) => 1000 + Number(n.slice(1));
const page = (names: string[], more: boolean) => ({ open: "in_progress", machines: names, more });
const head = all.slice(0, 20);

describe("the machine ledger's pages", () => {
  it("shows the machines of the snapshot's first page, and the older ones wait", () => {
    const p = paging(page(head, true), last);
    expect(shownRows(all, last, p)).toEqual(head);
  });

  it("shows every machine when the first page holds them all, or when the snapshot sends no page", () => {
    expect(shownRows(all, last, paging(page(all, false), last))).toEqual(all);
    expect(shownRows(all, last, null)).toEqual(all);
  });

  it("shows a machine newer than the page at once, and one that has no activity only once nothing older remains", () => {
    const fresh = ["fresh", ...all], at = (n: string) => (n === "fresh" ? 5000 : n === "idle" ? 0 : last(n));
    const p = paging(page(head, true), at);
    expect(shownRows(fresh, at, p)[0]).toBe("fresh");
    expect(shownRows([...fresh, "idle"], at, p)).not.toContain("idle");
    expect(shownRows([...all, "idle"], at, paging(page([...all, "idle"], false), at))).toContain("idle");
  });

  it("asks for the next page only when the footer is in view, older machines remain and no request is out", () => {
    const p = paging(page(head, true), last);
    expect(wantNext(p, false, 10)).toBe(false);
    expect(wantNext(p, true, 10)).toBe(true);
    expect(wantNext(asked(p), true, 10)).toBe(false);
    expect(wantNext(paging(page(all, false), last), true, 10)).toBe(false);
    expect(wantNext(null, true, 10)).toBe(false);
  });

  it("asks for the machines entered from the open one that are older than the oldest it holds", () => {
    const p = paging(page(head, true), last);
    expect(nextQuery(p)).toBe("/api/machines?open=in_progress&before=1010&limit=20");
  });

  it("takes the next page without repeating a row, even when the page overlaps the last", () => {
    const p = paging(page(head, true), last);
    const next = arrived(p, [...all.slice(19, 30)].map((name) => ({ name, last: last(name) })), false);
    const shown = shownRows(all, last, next);
    expect(shown).toEqual(all);
    expect(new Set(shown).size).toBe(shown.length);
    expect(wantNext(next, true, 10)).toBe(false);
  });

  it("walks a thousand machines twenty at a time, each once", () => {
    const names = Array.from({ length: 1000 }, (_, i) => `n${999 - i}`), at = (n: string) => 1 + Number(n.slice(1));
    let p = paging(page(names.slice(0, 20), true), at), calls = 0;
    while (wantNext(p, true, 0)) {
      const before = Number(new URL(nextQuery(p), "http://x").searchParams.get("before")), older = names.filter((n) => at(n) < before);
      p = arrived(asked(p), older.slice(0, 20).map((name) => ({ name, last: at(name) })), older.length > 20);
      calls++;
    }
    expect(calls).toBe(49);
    expect(shownRows(names, at, p)).toEqual(names);
  });

  it("retries a failed request after a few seconds, not at once", () => {
    const p = failed(asked(paging(page(head, true), last)), 100);
    expect(wantNext(p, true, 101)).toBe(false);
    expect(wantNext(p, true, 106)).toBe(true);
  });

  it("starts over when the open machine changes", () => {
    const p = paging(page(head, true), last);
    expect(paging({ ...page(head, true), open: "triaging" }, last).top).not.toBe(p.top);
  });

  it("loads the page a revealed row is on, and the rows between, without asking the server", () => {
    const p = paging(page(head, true), last), at = reveal(p, last("m3"));
    expect(shownRows(all, last, at)).toEqual(all.slice(0, 27));
    expect(reveal(p, last("m25"))).toBe(p);
    expect(nextQuery(at)).toContain("before=1003");
  });
});
