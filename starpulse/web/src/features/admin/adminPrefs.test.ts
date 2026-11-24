import { describe, expect, it, vi } from "vitest";
import { ADMIN_DEFAULTS, AdminStore, applyScale, clampScale, labelPx, loadAdmin } from "./adminPrefs";

/** A server that answers each GET with `held` and each PUT with `put`. */
const server = (held: unknown = {}, put: { ok: boolean; status?: number; body?: unknown } = { ok: true }) => {
  const calls: { method: string; body?: unknown }[] = [];
  const fetcher = vi.fn(async (_url: string, init?: { method?: string; body?: string }) => {
    const method = init?.method ?? "GET";
    calls.push({ method, body: init?.body ? JSON.parse(init.body) : undefined });
    if (method === "GET") return new Response(JSON.stringify({ display: held }));
    return new Response(JSON.stringify(put.body ?? {}), { status: put.ok ? 200 : (put.status ?? 400) });
  });
  return { fetcher: fetcher as never, calls };
};
const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
const root = () => {
  const vars = new Map<string, string>(), classes = new Set<string>();
  return {
    vars, classes,
    style: { setProperty: (n: string, v: string) => void vars.set(n, v) },
    classList: { toggle: (n: string, on?: boolean) => void (on ? classes.add(n) : classes.delete(n)) },
  };
};

describe("the font size every device shares", () => {
  it("falls back to 100 % when the server holds nothing, garbage or the wrong type", () => {
    expect(loadAdmin(undefined)).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin(null)).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin("{not json")).toEqual(ADMIN_DEFAULTS);
    expect(loadAdmin({ scale: "big" })).toEqual(ADMIN_DEFAULTS);
  });

  it("holds the scale to 85-150 % in steps of 5", () => {
    expect([0, 84, 85, 100, 132, 133, 150, 151, 999].map(clampScale)).toEqual([85, 85, 85, 100, 130, 135, 150, 150, 150]);
    expect([NaN, Infinity, "130", null, undefined].map(clampScale)).toEqual([100, 100, 100, 100, 100]);
    // a held out-of-range value cannot break the page
    expect(loadAdmin({ scale: 400 })).toEqual({ ...ADMIN_DEFAULTS, scale: 150 });
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

  it("starts on the defaults, adopts what the server holds, and sends only the field a change names", async () => {
    const r = root(), seen = vi.fn(), { fetcher, calls } = server();
    const store = new AdminStore(r, fetcher);
    store.subscribe(seen);
    expect(store.get()).toEqual(ADMIN_DEFAULTS);

    store.adopt({ display: { scale: 115 } });
    await store.loaded;
    expect(store.get().scale).toBe(115);
    expect(r.vars.get("--fs")).toBe("1.15");
    expect(calls).toEqual([]);

    store.setScale(150);
    await settle();
    expect(r.vars.get("--fs")).toBe("1.5");
    expect(calls).toEqual([{ method: "PUT", body: { display: { scale: 150 } } }]);

    store.setScale(9000);
    expect(store.get().scale).toBe(150);
  });

  it("resets every setting to the defaults and keeps them for every device", async () => {
    const r = root(), { fetcher, calls } = server();
    const store = new AdminStore(r, fetcher);
    store.adopt({ display: { scale: 130, motion: false } });

    store.reset();
    await settle();
    expect(store.get()).toEqual(ADMIN_DEFAULTS);
    expect(r.vars.get("--fs")).toBe("1");
    expect(r.classes.has("still")).toBe(false);
    expect(calls).toEqual([{ method: "PUT", body: { display: { scale: 100, motion: true } } }]);
  });
});

describe("the motion, opening view, card density and clock every device shares", () => {
  it("defaults to motion on, the Star Map, comfortable cards and a 24-hour clock", () => {
    expect(ADMIN_DEFAULTS).toEqual({ scale: 100, motion: true, view: "constellation", density: "comfortable", clock: "24" });
  });

  it("reads each setting back from the server and ignores a value it does not know", () => {
    expect(loadAdmin({ scale: 115, motion: false, view: "kanban", density: "compact", clock: "12" })).toEqual({ scale: 115, motion: false, view: "kanban", density: "compact", clock: "12" });
    expect(loadAdmin({ motion: "no", view: "admin", density: "tiny", clock: 12 })).toEqual(ADMIN_DEFAULTS);
  });

  it("sends each setter's field alone, tells the listeners once per change, and says Saved", async () => {
    const r = root(), seen = vi.fn(), { fetcher, calls } = server();
    const store = new AdminStore(r, fetcher);
    store.subscribe(seen);

    store.setMotion(false);
    store.setView("kanban");
    store.setDensity("compact");
    store.setClock("12");
    store.setClock("12");
    await settle();

    expect(store.get()).toEqual({ scale: 100, motion: false, view: "kanban", density: "compact", clock: "12" });
    expect(calls.map((c) => c.body)).toEqual([{ display: { motion: false } }, { display: { view: "kanban" } }, { display: { density: "compact" } }, { display: { clock: "12" } }]);
    expect(store.saved()).toEqual({ kind: "saved" });
  });

  it("stills the page with the `still` class while motion is off, at start and on each change", () => {
    const r = root(), { fetcher } = server();
    const store = new AdminStore(r, fetcher);
    store.adopt({ display: { motion: false } });
    expect(r.classes.has("still")).toBe(true);

    store.setMotion(true);
    expect(r.classes.has("still")).toBe(false);
    store.setMotion(false);
    expect(r.classes.has("still")).toBe(true);
  });

  it("names the server's reason when it refuses, and draws what the server holds", async () => {
    const r = root(), { fetcher } = server({ scale: 100 }, { ok: false, body: { error: "scale must be 85 to 150" } });
    const store = new AdminStore(r, fetcher);

    store.setScale(130);
    expect(store.get().scale).toBe(130);
    await settle();

    expect(store.saved()).toEqual({ kind: "refused", reason: "scale must be 85 to 150" });
    expect(store.get().scale).toBe(100);
    expect(r.vars.get("--fs")).toBe("1");
  });

  it("says the server did not answer when the request fails", async () => {
    const store = new AdminStore(root(), (async () => { throw new Error("offline"); }) as never);

    store.setClock("12");
    await settle();

    expect(store.saved()).toEqual({ kind: "refused", reason: "the server did not answer" });
  });
});
