import { describe, expect, it, vi } from "vitest";
import { ADMIN_KEY, AdminStore, applyScale, clampScale, labelPx, loadAdmin, saveAdmin } from "./adminPrefs";
import type { FoldStorage } from "./nav";

const memory = (): FoldStorage & { data: Map<string, string> } => {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
};
const off: FoldStorage = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
const root = () => {
  const vars = new Map<string, string>();
  return { vars, style: { setProperty: (n: string, v: string) => void vars.set(n, v) } };
};

describe("the font size kept for this browser", () => {
  it("falls back to 100 % when nothing, garbage or a denied storage is there", () => {
    const bad = memory();
    bad.data.set(ADMIN_KEY, "{not json");
    const wrongType = memory();
    wrongType.data.set(ADMIN_KEY, JSON.stringify({ scale: "big" }));

    expect(loadAdmin(memory())).toEqual({ scale: 100 });
    expect(loadAdmin(bad)).toEqual({ scale: 100 });
    expect(loadAdmin(wrongType)).toEqual({ scale: 100 });
    expect(loadAdmin(off)).toEqual({ scale: 100 });
    expect(loadAdmin(null)).toEqual({ scale: 100 });
  });

  it("reads back what it wrote under fv.admin.prefs", () => {
    const storage = memory();
    saveAdmin(storage, { scale: 130 });

    expect(JSON.parse(storage.data.get("fv.admin.prefs")!)).toEqual({ scale: 130 });
    expect(loadAdmin(storage)).toEqual({ scale: 130 });
  });

  it("keeps the session's choice when storage is denied on write", () => {
    expect(() => saveAdmin(off, { scale: 130 })).not.toThrow();
  });

  it("holds the scale to 85-150 % in steps of 5", () => {
    expect([0, 84, 85, 100, 132, 133, 150, 151, 999].map(clampScale)).toEqual([85, 85, 85, 100, 130, 135, 150, 150, 150]);
    expect([NaN, Infinity, "130", null, undefined].map(clampScale)).toEqual([100, 100, 100, 100, 100]);
    // a stored out-of-range value cannot break the page
    const storage = memory();
    storage.data.set(ADMIN_KEY, JSON.stringify({ scale: 400 }));
    expect(loadAdmin(storage)).toEqual({ scale: 150 });
  });
});

describe("the scale reaching the page", () => {
  it("sets the --fs variable every CSS font size multiplies", () => {
    const r = root();
    applyScale(130, r);
    expect(r.vars.get("--fs")).toBe("1.3");
    applyScale(85, r);
    expect(r.vars.get("--fs")).toBe("0.85");
  });

  it("sizes a canvas label by the scale, still a fixed size on screen at any zoom", () => {
    expect(labelPx(12.5, 1, 100)).toBe(12.5);
    expect(labelPx(12.5, 1, 130)).toBeCloseTo(16.25);
    expect(labelPx(12.5, 2, 130)).toBeCloseTo(8.125);
  });

  it("applies the stored scale at start, then each change to the variable, the storage and the listeners", () => {
    const storage = memory(), r = root(), seen = vi.fn();
    saveAdmin(storage, { scale: 115 });
    const store = new AdminStore(storage, r);
    store.subscribe(seen);
    expect(store.get().scale).toBe(115);
    expect(r.vars.get("--fs")).toBe("1.15");

    store.setScale(150);
    expect(store.get().scale).toBe(150);
    expect(r.vars.get("--fs")).toBe("1.5");
    expect(loadAdmin(storage)).toEqual({ scale: 150 });
    expect(seen).toHaveBeenCalledTimes(1);

    store.setScale(9000);
    expect(store.get().scale).toBe(150);
  });

  it("resets this browser to 100 % and forgets the stored choice", () => {
    const storage = memory(), r = root();
    const store = new AdminStore(storage, r);
    store.setScale(130);

    store.reset();
    expect(store.get().scale).toBe(100);
    expect(r.vars.get("--fs")).toBe("1");
    expect(loadAdmin(storage)).toEqual({ scale: 100 });
  });
});
