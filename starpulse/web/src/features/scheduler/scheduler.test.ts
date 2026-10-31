import { describe, expect, it, vi } from "vitest";
import { ROUTES } from "../../demo/demo";
import { SchedulerStore, level, type Dimension } from "./scheduler";

/** What `GET /api/scheduler` answers today: the switch, harness, when the sampler last read, and each dimension's use against its limit. */
const STATUS = {
  enabled: true,
  harness: "claude",
  sampledAt: 100,
  sessionCap: { harness: "claude", limit: 4, source: "starpulse.toml", configLimit: 4 },
  dimensions: [
    { name: "cpu", use: 41, limit: 80 },
    { name: "memory", use: 58, limit: 85 },
    { name: "sessions", use: 2, limit: 4 },
    { name: "review", use: 13, limit: 24 },
  ],
};
const HARNESSES = {
  tiers: ["fast", "standard"],
  harnesses: [
    { name: "claude", label: "Claude Code", sessions: true, reason: "", tiers: {} },
    { name: "cursor", label: "Cursor", sessions: true, reason: "", tiers: {} },
  ],
};
const IN_FLIGHT = [{ task: "TASK-1", title: "First", model: "opus · high", started: 40, url: "#demo-session-0001" }];
const NEXT = { task: "TASK-2", title: "Second", verdict: "waits", reason: "Sessions 4/4" };

const answer = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

/** A server that keeps the switch and harness as the route does: a PUT sets them and the answer follows; a bad body is refused. */
function server(opts: { down?: boolean; body?: unknown; status?: number } = {}) {
  let enabled = true;
  let harness = "claude";
  let cap: number | null = null;
  return vi.fn<typeof fetch>((url, init) => {
    if (opts.down) return Promise.reject(new Error("offline"));
    if (String(url).endsWith("/api/harnesses")) return answer(HARNESSES);
    if (opts.body !== undefined) return answer(opts.body, opts.status);
    if (init?.method === "PUT") {
      const sent = JSON.parse(String(init.body)) as { enabled?: unknown; harness?: unknown; sessionCap?: unknown };
      if ("sessionCap" in sent) {
        if (sent.sessionCap !== null && !(Number.isInteger(sent.sessionCap) && (sent.sessionCap as number) > 0)) {
          return answer({ error: "session cap must be a whole number above zero" }, 400);
        }
        cap = sent.sessionCap as number | null;
      }
      if (sent.enabled !== undefined && typeof sent.enabled !== "boolean") {
        return answer({ error: 'the scheduler takes {"enabled": true} or {"enabled": false}' }, 400);
      }
      if (sent.harness !== undefined && (typeof sent.harness !== "string" || !sent.harness)) {
        return answer({ error: "harness must be a non-empty string" }, 400);
      }
      if (sent.enabled === undefined && sent.harness === undefined && !("sessionCap" in sent)) {
        return answer({ error: "the scheduler takes enabled and/or harness" }, 400);
      }
      if (typeof sent.enabled === "boolean") enabled = sent.enabled;
      if (typeof sent.harness === "string") harness = sent.harness;
    }
    const sessionCap = { harness, limit: cap ?? 4, source: cap === null ? "starpulse.toml" : "admin", configLimit: 4 };
    return answer({ ...STATUS, enabled, harness, sessionCap });
  });
}

describe("the Autopilot card's store", () => {
  it("reads the switch and each dimension's use against its limit, with the label and unit the card draws", async () => {
    const store = new SchedulerStore(server());

    await store.load();

    const current = store.get().current!;
    expect(current.on).toBe(true);
    expect(current.harness).toBe("claude");
    expect(current.dimensions.map((d) => [d.name, d.label, d.used, d.limit, d.unit])).toEqual([
      ["cpu", "CPU", 41, 80, "%"],
      ["memory", "RAM", 58, 85, "%"],
      ["sessions", "Sessions", 2, 4, ""],
      ["review", "Review", 13, 24, " pts"],
    ]);
    expect(current.dimensions[0].detail).toContain("80%");
    expect(store.get().unavailable).toBe("");
    expect(store.get().harnesses.map((h) => h.name)).toEqual(["claude", "cursor"]);
  });

  it("defaults the harness to claude and carries pauses and per-harness session use when the server serves them", async () => {
    const pauses = [{ harness: "claude", until: 75_600, reason: "usage limit" }];
    const sessionsByHarness = { claude: { use: 1, limit: 3 }, cursor: { use: 0, limit: 2 } };
    const store = new SchedulerStore(server({
      body: { ...STATUS, harness: undefined, pauses, sessionsByHarness },
    }));

    await store.load();

    expect(store.get().current).toMatchObject({ harness: "claude", pauses, sessionsByHarness });
  });

  it("selects another harness with a PUT and shows the answer", async () => {
    const fetcher = server();
    const store = new SchedulerStore(fetcher);
    await store.load();

    await store.setHarness("cursor");

    expect(fetcher).toHaveBeenLastCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ harness: "cursor" }) });
    expect(store.get().current?.harness).toBe("cursor");
    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("has no session list and no pick while the server serves neither", async () => {
    const store = new SchedulerStore(server());

    await store.load();

    expect(store.get().current).toMatchObject({ inFlight: null, next: null });
  });

  it("carries the session list and the next pick when the server serves them", async () => {
    const store = new SchedulerStore(server({ body: { ...STATUS, inFlight: IN_FLIGHT, next: NEXT } }));

    await store.load();

    expect(store.get().current).toMatchObject({ inFlight: IN_FLIGHT, next: NEXT });
  });

  it("reads a dimension the card has no label for under its own name", async () => {
    const store = new SchedulerStore(server({ body: { ...STATUS, dimensions: [{ name: "gpu", use: 1, limit: 2 }] } }));

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
    const store = new SchedulerStore(server());
    await store.load();
    const bad = new SchedulerStore(server({ body }));
    await bad.load();

    expect(bad.get()).toMatchObject({ current: null, unavailable: "the server's answer is not a scheduler status" });
    expect(store.get().current).not.toBeNull();
  });

  it("names why the status cannot be read", async () => {
    const down = new SchedulerStore(server({ down: true }));
    const none = new SchedulerStore(server({ body: { error: "this instance runs no scheduler" }, status: 404 }));

    await down.load();
    await none.load();

    expect(down.get()).toMatchObject({ current: null, unavailable: "the server did not answer" });
    expect(none.get()).toMatchObject({ current: null, unavailable: "this instance runs no scheduler" });
  });

  it("keeps the last reading when a later read fails", async () => {
    const fetcher = server();
    const store = new SchedulerStore(fetcher);
    await store.load();
    fetcher.mockImplementationOnce(() => Promise.reject(new Error("offline")));

    await store.load();

    expect(store.get().current?.on).toBe(true);
    expect(store.get().unavailable).toBe("the server did not answer");
  });

  it("turns admission off by PUTting {enabled} and shows the answer", async () => {
    const fetcher = server();
    const store = new SchedulerStore(fetcher);
    await store.load();

    await store.setOn(false);

    expect(fetcher).toHaveBeenLastCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ enabled: false }) });
    expect(store.get().current?.on).toBe(false);
    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("says why a change was refused, leaves the switch as it was, and clears on dismiss", async () => {
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      init?.method === "PUT" ? answer({ error: "Autopilot changes are taken only from loopback or a private address" }, 403) : answer(STATUS));
    const store = new SchedulerStore(fetcher);
    await store.load();

    await store.setOn(false);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "Autopilot changes are taken only from loopback or a private address" });
    expect(store.get().current?.on).toBe(true);

    store.dismiss();

    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("says the change did not reach the server when the server is down", async () => {
    const store = new SchedulerStore(server({ down: true }));

    await store.setOn(false);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "the change did not reach the server" });
  });

  it("reads the session cap with where it comes from, and null while the server does not serve it", async () => {
    const store = new SchedulerStore(server());
    await store.load();
    expect(store.get().current!.sessionCap).toEqual({ harness: "claude", limit: 4, source: "starpulse.toml", configLimit: 4 });

    const bare = new SchedulerStore(server({ body: { ...STATUS, sessionCap: undefined } }));
    await bare.load();
    expect(bare.get().current!.sessionCap).toBeNull();
  });

  it("sets the session cap by PUTting {sessionCap} and clears it with null", async () => {
    const fetcher = server();
    const store = new SchedulerStore(fetcher);
    await store.load();

    await store.setSessionCap(7);
    expect(fetcher).toHaveBeenLastCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ sessionCap: 7 }) });
    expect(store.get().current!.sessionCap).toEqual({ harness: "claude", limit: 7, source: "admin", configLimit: 4 });

    await store.setSessionCap(null);
    expect(fetcher).toHaveBeenLastCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ sessionCap: null }) });
    expect(store.get().current!.sessionCap!.source).toBe("starpulse.toml");
  });

  it("says why the server refused a session cap and keeps the one it had", async () => {
    const store = new SchedulerStore(server());
    await store.load();

    await store.setSessionCap(0);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "session cap must be a whole number above zero" });
    expect(store.get().current!.sessionCap!.limit).toBe(4);
  });

  it("sends one change at a time", async () => {
    const fetcher = server();
    const store = new SchedulerStore(fetcher);
    await store.load();
    fetcher.mockClear();

    await Promise.all([store.setOn(false), store.setOn(true)]);

    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("is a route the public demo serves", () => {
    expect(ROUTES["/api/scheduler"]).toBeNull();
  });
});

describe("a meter's level", () => {
  const d = (used: number, limit = 10): Dimension => ({ name: "sessions", label: "Sessions", used, limit, unit: "", detail: "" });

  it("is quiet under 80% of the limit, near from there to the limit, and over past it", () => {
    expect([d(7), d(8), d(10), d(11)].map(level)).toEqual(["ok", "near", "near", "over"]);
  });
});
