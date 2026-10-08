import { describe, expect, it } from "vitest";
import { DAG_PREFS_KEY, loadFilters, NO_DAG_FILTERS, saveFilters } from "./viewPrefs";

const memory = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) }; };

describe("view filters", () => {
  it("round-trips what a view saved", () => {
    const s = memory(), f = { q: "lint", only: "failed", dom: "ops", win: null };
    saveFilters(s, DAG_PREFS_KEY, f);
    expect(loadFilters(s, DAG_PREFS_KEY, NO_DAG_FILTERS)).toEqual(f);
  });
  it("starts empty with nothing kept, junk, or no storage", () => {
    const s = memory();
    expect(loadFilters(s, DAG_PREFS_KEY, NO_DAG_FILTERS)).toEqual(NO_DAG_FILTERS);
    s.setItem(DAG_PREFS_KEY, "{not json");
    expect(loadFilters(s, DAG_PREFS_KEY, NO_DAG_FILTERS)).toEqual(NO_DAG_FILTERS);
    expect(loadFilters(null, DAG_PREFS_KEY, NO_DAG_FILTERS)).toEqual(NO_DAG_FILTERS);
  });
  it("keeps the fallback for a field of the wrong type", () => {
    const s = memory();
    s.setItem(DAG_PREFS_KEY, JSON.stringify({ q: 3, only: "failed", dom: [1] }));
    expect(loadFilters(s, DAG_PREFS_KEY, NO_DAG_FILTERS)).toEqual({ ...NO_DAG_FILTERS, only: "failed" });
  });
});
