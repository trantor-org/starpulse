import { describe, expect, it, vi } from "vitest";
import { ROUTES } from "../../demo/demo";
import { AutopilotStore, level, type Dimension } from "./autopilot";

/** What `GET /api/autopilot` answers today: the switch, when the sampler last read, and each dimension's use against its limit. */
const STATUS = {
  enabled: true,
  sampledAt: 100,
  dimensions: [
    { name: "cpu", use: 41, limit: 80 },
    { name: "memory", use: 58, limit: 85 },
    { name: "sessions", use: 2, limit: 4 },
    { name: "review", use: 13, limit: 24 },
  ],
};
const IN_FLIGHT = [{ task: "TASK-1", title: "First", model: "opus · high", started: 40, url: "#demo-session-0001" }];
const NEXT = { task: "TASK-2", title: "Second", verdict: "waits", reason: "Sessions 4/4" };

const answer = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

/** A server that keeps the switch as the route does: a PUT sets it and the answer follows it; anything but a boolean is refused. */
function server(opts: { down?: boolean; body?: unknown; status?: number } = {}) {
  let enabled = true;
  return vi.fn<typeof fetch>((_url, init) => {
    if (opts.down) return Promise.reject(new Error("offline"));
    if (opts.body !== undefined) return answer(opts.body, opts.status);
    if (init?.method === "PUT") {
      const sent = (JSON.parse(String(init.body)) as { enabled: unknown }).enabled;
      if (typeof sent !== "boolean") return answer({ error: 'the autopilot takes {"enabled": true} or {"enabled": false}' }, 400);
      enabled = sent;
    }
    return answer({ ...STATUS, enabled });
  });
}

describe("the autopilot strip's store", () => {
  it("reads the switch and each dimension's use against its limit, with the label and unit the strip draws", async () => {
    const store = new AutopilotStore(server());

    await store.load();

    const current = store.get().current!;
    expect(current.on).toBe(true);
    expect(current.dimensions.map((d) => [d.name, d.label, d.used, d.limit, d.unit])).toEqual([
      ["cpu", "CPU", 41, 80, "%"],
      ["memory", "RAM", 58, 85, "%"],
      ["sessions", "Sessions", 2, 4, ""],
      ["review", "Review", 13, 24, " pts"],
    ]);
    expect(current.dimensions[0].detail).toContain("80%");
    expect(store.get().unavailable).toBe("");
  });

  it("has no session list and no pick while the server serves neither", async () => {
    const store = new AutopilotStore(server());

    await store.load();

    expect(store.get().current).toMatchObject({ inFlight: null, next: null });
  });

  it("carries the session list and the next pick when the server serves them", async () => {
    const store = new AutopilotStore(server({ body: { ...STATUS, inFlight: IN_FLIGHT, next: NEXT } }));

    await store.load();

    expect(store.get().current).toMatchObject({ inFlight: IN_FLIGHT, next: NEXT });
  });

  it("reads a dimension the strip has no label for under its own name", async () => {
    const store = new AutopilotStore(server({ body: { ...STATUS, dimensions: [{ name: "gpu", use: 1, limit: 2 }] } }));

    await store.load();

    expect(store.get().current?.dimensions[0]).toMatchObject({ name: "gpu", label: "gpu", unit: "" });
  });

  it.each([
    ["dimensions that are not an array", { ...STATUS, dimensions: "cpu" }],
    ["a switch that is not a boolean", { ...STATUS, enabled: "yes" }],
    ["a dimension with no limit", { ...STATUS, dimensions: [{ name: "cpu", use: 1 }] }],
    ["an inFlight that is not an array", { ...STATUS, inFlight: "TASK-1" }],
    ["an inFlight entry with no task", { ...STATUS, inFlight: [{ title: "First" }] }],
    ["a next with no task", { ...STATUS, next: { verdict: "waits" } }],
  ])("refuses an answer with %s and keeps the last good reading", async (_why, body) => {
    const store = new AutopilotStore(server());
    await store.load();
    const bad = new AutopilotStore(server({ body }));
    await bad.load();

    expect(bad.get()).toMatchObject({ current: null, unavailable: "the server's answer is not an autopilot status" });
    expect(store.get().current).not.toBeNull();
  });

  it("names why the status cannot be read", async () => {
    const down = new AutopilotStore(server({ down: true }));
    const none = new AutopilotStore(server({ body: { error: "this instance runs no autopilot" }, status: 404 }));

    await down.load();
    await none.load();

    expect(down.get()).toMatchObject({ current: null, unavailable: "the server did not answer" });
    expect(none.get()).toMatchObject({ current: null, unavailable: "this instance runs no autopilot" });
  });

  it("keeps the last reading when a later read fails", async () => {
    const fetcher = server();
    const store = new AutopilotStore(fetcher);
    await store.load();
    fetcher.mockImplementationOnce(() => Promise.reject(new Error("offline")));

    await store.load();

    expect(store.get().current?.on).toBe(true);
    expect(store.get().unavailable).toBe("the server did not answer");
  });

  it("turns admission off by PUTting {enabled} and shows the answer", async () => {
    const fetcher = server();
    const store = new AutopilotStore(fetcher);
    await store.load();

    await store.setOn(false);

    expect(fetcher).toHaveBeenLastCalledWith("/api/autopilot", { method: "PUT", body: JSON.stringify({ enabled: false }) });
    expect(store.get().current?.on).toBe(false);
    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("says why a change was refused, leaves the switch as it was, and clears on dismiss", async () => {
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      init?.method === "PUT" ? answer({ error: "Autopilot changes are taken only from loopback or a private address" }, 403) : answer(STATUS));
    const store = new AutopilotStore(fetcher);
    await store.load();

    await store.setOn(false);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "Autopilot changes are taken only from loopback or a private address" });
    expect(store.get().current?.on).toBe(true);

    store.dismiss();

    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("says the change did not reach the server when the server is down", async () => {
    const store = new AutopilotStore(server({ down: true }));

    await store.setOn(false);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "the change did not reach the server" });
  });

  it("sends one change at a time", async () => {
    const fetcher = server();
    const store = new AutopilotStore(fetcher);
    await store.load();
    fetcher.mockClear();

    await Promise.all([store.setOn(false), store.setOn(true)]);

    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("is a route the public demo serves", () => {
    expect(ROUTES["/api/autopilot"]).toBeNull();
  });
});

describe("a meter's level", () => {
  const d = (used: number, limit = 10): Dimension => ({ name: "sessions", label: "Sessions", used, limit, unit: "", detail: "" });

  it("is quiet under 80% of the limit, near from there to the limit, and over past it", () => {
    expect([d(7), d(8), d(10), d(11)].map(level)).toEqual(["ok", "near", "near", "over"]);
  });
});
