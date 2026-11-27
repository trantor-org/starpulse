import { afterEach, describe, expect, it, vi } from "vitest";
import { SchedulerStore, level, type Dimension } from "./scheduler";

/** What `GET /api/admin` answers today: the switch, harness, when the sampler last read, and each dimension's use against its limit. */
const STATUS = {
  position: 7,
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
    { name: "other", label: "Other", sessions: true, reason: "", tiers: {} },
  ],
};
const IN_FLIGHT = [{ task: "TASK-1", title: "First", model: "opus · high", started: 40, url: "#demo-session-0001" }];
const NEXT = { task: "TASK-2", title: "Second", verdict: "waits", reason: "Sessions 4/4" };

/** A store each test disposes after it ends, so no subscription it follows outlives the test file. */
const made: SchedulerStore[] = [];
class Store extends SchedulerStore {
  constructor(...args: ConstructorParameters<typeof SchedulerStore>) {
    super(...args);
    made.push(this);
  }
}
afterEach(() => made.splice(0).forEach((store) => store.dispose()));

const answer = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status }));

/** A `schedulerChanges` stream that sends each change and stays open, as the server's does while idle. */
const open = (...changes: unknown[]) =>
  new Response(new ReadableStream({ start(c) { for (const data of changes) c.enqueue(new TextEncoder().encode(`event: next\ndata: ${JSON.stringify({ data: { schedulerChanges: data } })}\n\n`)); } }), { headers: { "content-type": "text/event-stream" } });
const ended = () => new Response(new ReadableStream({ start: (c) => c.close() }), { headers: { "content-type": "text/event-stream" } });
/** What a `schedulerChanges` change carries for the same status: GraphQL has no maps, and a list a server may omit is null. */
const CHANGE = { ...STATUS, position: undefined, sessionCap: null, capacityLimits: null, inFlight: null, next: null, pauses: null, blockedBy: null, sessionsByHarness: null };

/** A server that keeps the switch and harness as the route does: a PUT sets them and the answer follows; a bad body is refused. */
function server(opts: { down?: boolean; body?: unknown; status?: number; graphql?: (opened: number) => Response } = {}) {
  let opened = 0;
  let enabled = true;
  let harness = "claude";
  let cap: number | null = null;
  const limits: Record<string, number | null> = { cpu: null, memory: null };
  return vi.fn<typeof fetch>((url, init) => {
    if (opts.down) return Promise.reject(new Error("offline"));
    if (String(url).endsWith("/api/harnesses")) return answer(HARNESSES);
    if (String(url).endsWith("/graphql")) return Promise.resolve((opts.graphql ?? (() => open()))(opened++));
    if (opts.body !== undefined) return answer(opts.body, opts.status);
    if (init?.method === "PUT") {
      const sent = JSON.parse(String(init.body)) as { enabled?: unknown; harness?: unknown; sessionCap?: unknown; cpuLimit?: unknown; memoryLimit?: unknown };
      for (const [name, value] of [["cpu", sent.cpuLimit], ["memory", sent.memoryLimit]] as const) {
        if (value === undefined) continue;
        if (value !== null && !(typeof value === "number" && value > 0 && value <= 100)) {
          return answer({ error: name + " limit must be a percent above 0 and at most 100" }, 400);
        }
        limits[name] = value;
      }
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
      if (sent.enabled === undefined && sent.harness === undefined && !("sessionCap" in sent) && !("cpuLimit" in sent) && !("memoryLimit" in sent)) {
        return answer({ error: "the scheduler takes enabled and/or harness" }, 400);
      }
      if (typeof sent.enabled === "boolean") enabled = sent.enabled;
      if (typeof sent.harness === "string") harness = sent.harness;
    }
    const sessionCap = { harness, limit: cap ?? 4, source: cap === null ? "starpulse.toml" : "admin", configLimit: 4 };
    const capacityLimits = Object.fromEntries([["cpu", 80], ["memory", 85]].map(([name, config]) => [name, { limit: limits[name] ?? config, source: limits[name] === null ? "starpulse.toml" : "admin", configLimit: config }]));
    return answer({ ...STATUS, enabled, harness, sessionCap, capacityLimits });
  });
}

describe("the Autopilot card's store", () => {
  it("follows schedulerChanges from the position the read answered and takes each change as the card's status", async () => {
    const byHarness = [{ harness: "claude", use: 1, limit: 3 }, { harness: "cursor", use: 0, limit: 2 }];
    const fetcher = server({ graphql: () => open({ ...CHANGE, enabled: false, inFlight: IN_FLIGHT, next: NEXT, sessionsByHarness: byHarness }) });
    const store = new Store(fetcher);

    await store.load();
    await vi.waitFor(() => expect(store.get().current?.on).toBe(false));

    const [, init] = fetcher.mock.calls.find(([url]) => String(url).endsWith("/graphql"))!;
    expect(JSON.parse(String(init?.body)).variables).toEqual({ from: 7 });
    expect(JSON.parse(String(init?.body)).query).toContain("schedulerChanges(from: $from)");
    expect(store.get().current).toMatchObject({ inFlight: IN_FLIGHT, next: NEXT, sessionsByHarness: { claude: { use: 1, limit: 3 }, cursor: { use: 0, limit: 2 } } });
    store.dispose();
  });

  it("reads again at once when the position is lost, and follows from the new one", async () => {
    const fetcher = server({ graphql: (n) => (n === 0 ? new Response("{}", { status: 410 }) : open()) });
    const store = new Store(fetcher);

    await store.load();
    await vi.waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url) === "/api/admin")).toHaveLength(2));
    await vi.waitFor(() => expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith("/graphql"))).toHaveLength(2));
    store.dispose();
  });

  it("reads again after a pause when the server closes the stream, and stops following once disposed", async () => {
    vi.useFakeTimers();
    const fetcher = server({ graphql: (n) => (n === 0 ? ended() : open()) });
    const store = new Store(fetcher);
    const reads = () => fetcher.mock.calls.filter(([url]) => String(url) === "/api/admin").length;

    await store.load();
    await vi.advanceTimersByTimeAsync(2_000);
    expect(reads()).toBe(1);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(reads()).toBe(2);

    store.dispose();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(reads()).toBe(2);
    vi.useRealTimers();
  });

  it("reads the switch and each dimension's use against its limit, with the label and unit the card draws", async () => {
    const store = new Store(server());

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
    expect(store.get().harnesses.map((h) => h.name)).toEqual(["claude", "other"]);
  });

  it("defaults the harness to claude and carries pauses and per-harness session use when the server serves them", async () => {
    const pauses = [{ harness: "claude", until: 75_600, reason: "usage limit" }];
    const sessionsByHarness = { claude: { use: 1, limit: 3 }, cursor: { use: 0, limit: 2 } };
    const store = new Store(server({
      body: { ...STATUS, harness: undefined, pauses, sessionsByHarness },
    }));

    await store.load();

    expect(store.get().current).toMatchObject({ harness: "claude", pauses, sessionsByHarness });
  });

  it("selects another harness with a PUT and shows the answer", async () => {
    const fetcher = server();
    const store = new Store(fetcher);
    await store.load();

    await store.setHarness("other");

    expect(fetcher).toHaveBeenLastCalledWith("/api/admin", { method: "PUT", body: JSON.stringify({ harness: "other" }) });
    expect(store.get().current?.harness).toBe("other");
    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("has no session list and no pick while the server serves neither", async () => {
    const store = new Store(server());

    await store.load();

    expect(store.get().current).toMatchObject({ inFlight: null, next: null });
  });

  it("carries the session list and the next pick when the server serves them", async () => {
    const store = new Store(server({ body: { ...STATUS, inFlight: IN_FLIGHT, next: NEXT } }));

    await store.load();

    expect(store.get().current).toMatchObject({ inFlight: IN_FLIGHT, next: NEXT });
  });

  it("reads a dimension the card has no label for under its own name", async () => {
    const store = new Store(server({ body: { ...STATUS, dimensions: [{ name: "gpu", use: 1, limit: 2 }] } }));

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
    const store = new Store(server());
    await store.load();
    const bad = new Store(server({ body }));
    await bad.load();

    expect(bad.get()).toMatchObject({ current: null, unavailable: "the server's answer is not a scheduler status" });
    expect(store.get().current).not.toBeNull();
  });

  it("names why the status cannot be read", async () => {
    const down = new Store(server({ down: true }));
    const none = new Store(server({ body: { error: "this instance runs no scheduler" }, status: 404 }));

    await down.load();
    await none.load();

    expect(down.get()).toMatchObject({ current: null, unavailable: "the server did not answer" });
    expect(none.get()).toMatchObject({ current: null, unavailable: "this instance runs no scheduler" });
  });

  it("keeps the last reading when a later read fails", async () => {
    const fetcher = server();
    const store = new Store(fetcher);
    await store.load();
    fetcher.mockImplementationOnce(() => Promise.reject(new Error("offline")));

    await store.load();

    expect(store.get().current?.on).toBe(true);
    expect(store.get().unavailable).toBe("the server did not answer");
  });

  it("turns admission off by PUTting {enabled} and shows the answer", async () => {
    const fetcher = server();
    const store = new Store(fetcher);
    await store.load();

    await store.setOn(false);

    expect(fetcher).toHaveBeenLastCalledWith("/api/admin", { method: "PUT", body: JSON.stringify({ enabled: false }) });
    expect(store.get().current?.on).toBe(false);
    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("says why a change was refused, leaves the switch as it was, and clears on dismiss", async () => {
    const fetcher = vi.fn<typeof fetch>((_url, init) =>
      init?.method === "PUT" ? answer({ error: "Autopilot changes are taken only from loopback or a private address" }, 403) : answer(STATUS));
    const store = new Store(fetcher);
    await store.load();

    await store.setOn(false);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "Autopilot changes are taken only from loopback or a private address" });
    expect(store.get().current?.on).toBe(true);

    store.dismiss();

    expect(store.get().phase).toEqual({ kind: "idle" });
  });

  it("says the change did not reach the server when the server is down", async () => {
    const store = new Store(server({ down: true }));

    await store.setOn(false);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "the change did not reach the server" });
  });

  it("reads the session cap with where it comes from, and null while the server does not serve it", async () => {
    const store = new Store(server());
    await store.load();
    expect(store.get().current!.sessionCap).toEqual({ harness: "claude", limit: 4, source: "starpulse.toml", configLimit: 4 });

    const bare = new Store(server({ body: { ...STATUS, sessionCap: undefined } }));
    await bare.load();
    expect(bare.get().current!.sessionCap).toBeNull();
  });

  it("reads the cpu and memory limits with where they come from, and null while the server does not serve them", async () => {
    const store = new Store(server());
    await store.load();
    expect(store.get().current!.capacityLimits).toEqual({
      cpu: { limit: 80, source: "starpulse.toml", configLimit: 80 },
      memory: { limit: 85, source: "starpulse.toml", configLimit: 85 },
    });

    const bare = new Store(server({ body: STATUS }));
    await bare.load();
    expect(bare.get().current!.capacityLimits).toBeNull();

    const broken = new Store(server({ body: { ...STATUS, capacityLimits: { cpu: { limit: "high" } } } }));
    await broken.load();
    expect(broken.get().current).toBeNull();
  });

  it.each([["cpu", "cpuLimit"], ["memory", "memoryLimit"]] as const)("sets the %s limit by PUTting {%s} and clears it with null", async (name, field) => {
    const fetcher = server();
    const store = new Store(fetcher);
    await store.load();

    await store.setLimit(name, 62.5);
    expect(fetcher).toHaveBeenLastCalledWith("/api/admin", { method: "PUT", body: JSON.stringify({ [field]: 62.5 }) });
    expect(store.get().current!.capacityLimits![name]).toMatchObject({ limit: 62.5, source: "admin" });

    await store.setLimit(name, null);
    expect(fetcher).toHaveBeenLastCalledWith("/api/admin", { method: "PUT", body: JSON.stringify({ [field]: null }) });
    expect(store.get().current!.capacityLimits![name].source).toBe("starpulse.toml");
  });

  it("says why the server refused a limit and keeps the one it had", async () => {
    const store = new Store(server());
    await store.load();

    await store.setLimit("cpu", 101);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "cpu limit must be a percent above 0 and at most 100" });
    expect(store.get().current!.capacityLimits!.cpu.limit).toBe(80);
  });

  it("reads every blocking gate with its use and limit, and the start-limit count", async () => {
    const blockedBy = [
      { name: "cpu", use: 95, limit: 80 },
      { name: "start-limit", use: 48, limit: 48, count: 3 },
    ];
    const store = new Store(server({ body: { ...STATUS, blockedBy } }));
    await store.load();
    expect(store.get().current!.blockedBy).toEqual([
      { name: "cpu", use: 95, limit: 80, count: null },
      { name: "start-limit", use: 48, limit: 48, count: 3 },
    ]);

    const bare = new Store(server({ body: { ...STATUS, blockedBy: undefined } }));
    await bare.load();
    expect(bare.get().current!.blockedBy).toEqual([]);
  });

  it("sets the session cap by PUTting {sessionCap} and clears it with null", async () => {
    const fetcher = server();
    const store = new Store(fetcher);
    await store.load();

    await store.setSessionCap(7);
    expect(fetcher).toHaveBeenLastCalledWith("/api/admin", { method: "PUT", body: JSON.stringify({ sessionCap: 7 }) });
    expect(store.get().current!.sessionCap).toEqual({ harness: "claude", limit: 7, source: "admin", configLimit: 4 });

    await store.setSessionCap(null);
    expect(fetcher).toHaveBeenLastCalledWith("/api/admin", { method: "PUT", body: JSON.stringify({ sessionCap: null }) });
    expect(store.get().current!.sessionCap!.source).toBe("starpulse.toml");
  });

  it("says why the server refused a session cap and keeps the one it had", async () => {
    const store = new Store(server());
    await store.load();

    await store.setSessionCap(0);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "session cap must be a whole number above zero" });
    expect(store.get().current!.sessionCap!.limit).toBe(4);
  });

  it("sends one change at a time", async () => {
    const fetcher = server();
    const store = new Store(fetcher);
    await store.load();
    fetcher.mockClear();

    await Promise.all([store.setOn(false), store.setOn(true)]);

    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("a meter's level", () => {
  const d = (used: number, limit = 10): Dimension => ({ name: "sessions", label: "Sessions", used, limit, unit: "", detail: "" });

  it("is quiet under 80% of the limit, near from there to the limit, and over past it", () => {
    expect([d(7), d(8), d(10), d(11)].map(level)).toEqual(["ok", "near", "near", "over"]);
  });
});
