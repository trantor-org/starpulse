import { describe, expect, it, vi } from "vitest";
import { ADMIN_DEFAULTS, ADMIN_KEY, AdminStore, applyScale, clampScale, labelPx, loadAdmin, saveAdmin } from "./adminPrefs";
import type { PrefStorage } from "../../shared/nav";

const memory = (): PrefStorage & { data: Map<string, string> } => {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
};
const off: PrefStorage = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
const root = () => {
  const vars = new Map<string, string>(), classes = new Set<string>();
  return {
    vars, classes,
    style: { setProperty: (n: string, v: string) => void vars.set(n, v) },
    classList: { toggle: (n: string, on?: boolean) => void (on ? classes.add(n) : classes.delete(n)) },
  };
};

describe("the font size kept for this browser", () => {
  it("falls back to 100 % when nothing, garbage or a denied storage is there", () => {
    const bad = memory();
    bad.data.set(ADMIN_KEY, "{not json");
    const wrongType = memory();
    wrongType.data.set(ADMIN_KEY, JSON.stringify({ scale: "big" }));

    expect(loadAdmin(memory())).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin(bad)).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin(wrongType)).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin(off)).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin(null)).toEqual(ADMIN_DEFAULTS);
  });

  it("reads back what it wrote under fv.admin.prefs", () => {
    const storage = memory();
    saveAdmin(storage, { ...ADMIN_DEFAULTS, scale: 130 });

    expect(JSON.parse(storage.data.get("fv.admin.prefs")!)).toEqual({ ...ADMIN_DEFAULTS, scale: 130 });
    expect(loadAdmin(storage)).toEqual({ ...ADMIN_DEFAULTS, scale: 130 });
  });

  it("keeps the session's choice when storage is denied on write", () => {
    expect(() => saveAdmin(off, ADMIN_DEFAULTS)).not.toThrow();
  });

  it("holds the scale to 85-150 % in steps of 5", () => {
    expect([0, 84, 85, 100, 132, 133, 150, 151, 999].map(clampScale)).toEqual([85, 85, 85, 100, 130, 135, 150, 150, 150]);
    expect([NaN, Infinity, "130", null, undefined].map(clampScale)).toEqual([100, 100, 100, 100, 100]);
    // a stored out-of-range value cannot break the page
    const storage = memory();
    storage.data.set(ADMIN_KEY, JSON.stringify({ scale: 400 }));
    expect(loadAdmin(storage)).toEqual({ ...ADMIN_DEFAULTS, scale: 150 });
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
    saveAdmin(storage, { ...ADMIN_DEFAULTS, scale: 115 });
    const store = new AdminStore(storage, r);
    store.subscribe(seen);
    expect(store.get().scale).toBe(115);
    expect(r.vars.get("--fs")).toBe("1.15");

    store.setScale(150);
    expect(store.get().scale).toBe(150);
    expect(r.vars.get("--fs")).toBe("1.5");
    expect(loadAdmin(storage)).toEqual({ ...ADMIN_DEFAULTS, scale: 150 });
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
    expect(loadAdmin(storage)).toEqual(ADMIN_DEFAULTS);
  });
});

describe("the motion, opening view, card density and clock kept for this browser", () => {
  it("defaults to motion on, the Star Map, comfortable cards and a 24-hour clock", () => {
    expect(ADMIN_DEFAULTS).toEqual({ scale: 100, motion: true, view: "constellation", density: "comfortable", clock: "24" });
  });

  it("reads each setting back from storage and ignores a value it does not know", () => {
    const good = memory(), bad = memory();
    good.data.set(ADMIN_KEY, JSON.stringify({ scale: 115, motion: false, view: "kanban", density: "compact", clock: "12" }));
    bad.data.set(ADMIN_KEY, JSON.stringify({ motion: "no", view: "admin", density: "tiny", clock: 12 }));

    expect(loadAdmin(good)).toEqual({ scale: 115, motion: false, view: "kanban", density: "compact", clock: "12" });
    expect(loadAdmin(bad)).toEqual(ADMIN_DEFAULTS);
  });

  it("persists each setter, tells the listeners once, and keeps the other settings", () => {
    const storage = memory(), r = root(), seen = vi.fn();
    const store = new AdminStore(storage, r);
    store.subscribe(seen);

    store.setMotion(false);
    store.setView("kanban");
    store.setDensity("compact");
    store.setClock("12");
    store.setClock("12");

    expect(store.get()).toEqual({ scale: 100, motion: false, view: "kanban", density: "compact", clock: "12" });
    expect(loadAdmin(storage)).toEqual(store.get());
    expect(seen).toHaveBeenCalledTimes(4);
  });

  it("stills the page with the `still` class while motion is off, at start and on each change", () => {
    const storage = memory(), r = root();
    saveAdmin(storage, { ...ADMIN_DEFAULTS, motion: false });
    const store = new AdminStore(storage, r);
    expect(r.classes.has("still")).toBe(true);

    store.setMotion(true);
    expect(r.classes.has("still")).toBe(false);
    store.setMotion(false);
    expect(r.classes.has("still")).toBe(true);
  });

  it("resets every setting, not only the font size", () => {
    const storage = memory(), r = root();
    const store = new AdminStore(storage, r);
    store.setScale(130);
    store.setMotion(false);
    store.setView("kanban");
    store.setDensity("compact");
    store.setClock("12");

    store.reset();
    expect(store.get()).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin(storage)).toEqual(ADMIN_DEFAULTS);
    expect(r.classes.has("still")).toBe(false);
    expect(r.vars.get("--fs")).toBe("1");
  });
});
