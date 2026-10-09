import { describe, expect, it } from "vitest";
import { keep, same } from "./same";

describe("keep", () => {
  it("returns the old value when nothing differs, and keeps every unchanged part of one that does", () => {
    const prev = { a: [{ id: "x", n: 1 }, { id: "y", n: 2 }], b: { c: 1 } };

    expect(keep(prev, structuredClone(prev))).toBe(prev);

    const next = keep(prev, { a: [{ id: "x", n: 1 }, { id: "y", n: 3 }], b: { c: 1 } });
    expect(next).not.toBe(prev);
    expect(next.a[0]).toBe(prev.a[0]);
    expect(next.a[1]).not.toBe(prev.a[1]);
    expect(next.b).toBe(prev.b);
  });

  it("pairs array entries by key, so an insert or a reorder keeps the entries that moved", () => {
    const prev = [{ id: "x", n: 1 }, { id: "y", n: 2 }];

    const next = keep(prev, [{ id: "new", n: 0 }, { id: "y", n: 2 }, { id: "x", n: 1 }], (e) => e.id);

    expect(next[1]).toBe(prev[1]);
    expect(next[2]).toBe(prev[0]);
  });

  it("takes the new value when the old one is absent, shorter or of another shape", () => {
    expect(keep(undefined, { a: 1 })).toEqual({ a: 1 });
    expect(keep([1], [1, 2])).toEqual([1, 2]);
    expect(keep({ a: 1 }, [1] as never)).toEqual([1]);
  });
});

describe("same", () => {
  it("compares JSON data structurally", () => {
    expect(same({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] })).toBe(true);
    expect(same({ a: 1 }, { a: 2 })).toBe(false);
    expect(same([1], { 0: 1 })).toBe(false);
  });
});
