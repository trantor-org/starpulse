import { describe, expect, it, vi } from "vitest";
import { DemoServer, ROUTES, type DemoFixture } from "./demo";
import { NO_HARNESSES, fetchHarnesses, postStart } from "./start";
import type { Machine, RawAgent } from "./types";

const machine = (initial: string, edges: [string, string, string][], final = ""): Machine => {
  const ids = [...new Set(edges.flatMap(([s, t]) => [s, t]))];
  return {
    states: ids.map((id) => ({ id, name: id, initial: id === initial, final: id === final })),
    transitions: edges.map(([source, target, event]) => ({ source, target, event })),
  };
};
const BOARD = machine("new", [
  ["new", "ready", "CREATE_READY"],
  ["ready", "in_progress", "CLAIM"],
  ["in_progress", "in_progress", "PR_OPENED"],
  ["in_progress", "review", "REVIEW"],
  ["review", "done", "MERGED"],
  ["done", "completed", "SWEEP"],
], "completed");
const DELIVERY = machine("start", [["start", "red", "RED"], ["red", "green", "GREEN"]]);
const card = (id: string, state: string): RawAgent => ({ id, title: id, state, model: "" });

function fixture(): DemoFixture {
  return {
    graphs: ["board", "in-progress", "runs"],
    dags: [],
    flows: [
      { name: "board", machine: BOARD, agents: [card("DEMO-1", "in_progress"), card("DEMO-2", "ready")] },
      {
        name: "in-progress",
        machine: DELIVERY,
        agents: [{ ...card("DEMO-1", "red"), task: "DEMO-1", steps: 4, trail: [{ state: "red", event: "RED", at: 50 }] }],
      },
    ],
    settled: {},
    error: null,
    now: 100,
    history: { "DEMO-1": [{ at: 10, from: null, to: "ready" }, { at: 20, from: "ready", to: "in_progress" }] },
  };
}
const body = async (r: Promise<Response>) => (await r).json();
const lane = (s: DemoServer, id: string) => s.snapshot.flows[0].agents.find((a) => a.id === id)?.state;

describe("the demo server", () => {
  it("answers a task's lane path from the embedded history", async () => {
    const s = new DemoServer(fixture());

    expect(await body(s.fetch("/api/history?task=DEMO-1"))).toEqual({
      task: "DEMO-1",
      path: [{ at: 10, from: null, to: "ready" }, { at: 20, from: "ready", to: "in_progress" }],
    });
    expect(await body(s.fetch("/api/history?task=DEMO-9"))).toEqual({ task: "DEMO-9", path: [] });
  });

  it("answers a machine path from the task's trail on that machine, with its step total", async () => {
    const s = new DemoServer(fixture());

    expect(await body(s.fetch("/api/history?task=DEMO-1&flow=in-progress"))).toEqual({
      task: "DEMO-1",
      flow: "in-progress",
      path: [{ at: 50, event: "RED", state: "red" }],
      steps: 4,
    });
    expect((await s.fetch("/api/history?task=DEMO-1&flow=nowhere")).status).toBe(404);
  });

  it("gives each Board card a verdict for every column its lane exits to", () => {
    const s = new DemoServer(fixture());

    const [inProgress, ready] = s.snapshot.flows[0].agents;
    expect(inProgress.moves).toEqual({ review: { allowed: true, reason: "", skill: "" } });
    expect(Object.keys(ready.moves!)).toEqual(["in_progress"]);
  });

  it("moves a card, records the lane change and pushes the Board with the card in its new lane", async () => {
    const s = new DemoServer(fixture(), () => 30);
    const seen = vi.fn();
    s.subscribe(seen);

    const reply = await s.fetch("/api/move", { method: "POST", body: JSON.stringify({ task: "DEMO-1", to: "review" }) });

    expect(reply.status).toBe(200);
    expect(lane(s, "DEMO-1")).toBe("review");
    expect(seen).toHaveBeenCalledWith(s.snapshot);
    expect(s.snapshot.flows[0].agents[0].moves).toEqual({ done: { allowed: true, reason: "", skill: "" } });
    expect((await body(s.fetch("/api/history?task=DEMO-1"))).path.at(-1)).toEqual({ at: 30, from: "in_progress", to: "review" });
  });

  it("refuses a move to a column the card's lane does not exit to", async () => {
    const s = new DemoServer(fixture());

    const reply = await s.fetch("/api/move", { method: "POST", body: JSON.stringify({ task: "DEMO-2", to: "done" }) });

    expect(reply.status).toBe(409);
    expect((await reply.json()).error).toMatch(/ready to done/);
    expect(lane(s, "DEMO-2")).toBe("ready");
  });

  it("records the lane change of every card its walk moves", () => {
    const s = new DemoServer(fixture(), () => 40);
    const before = s.snapshot.flows[0].agents.map((a) => a.state);

    for (let i = 0; i < 20; i++) s.step();

    for (const a of s.snapshot.flows[0].agents) {
      const path = s.lanes[a.id] ?? [];
      if (a.state !== before[s.snapshot.flows[0].agents.indexOf(a)]) expect(path.at(-1)?.to).toBe(a.state);
    }
  });

  it("keeps its Board full: a card the walk settles comes back as a new task in the first lane", () => {
    const f = fixture();
    f.flows[0].machine = { ...BOARD, mainLine: ["new", "ready", "in_progress", "review", "done"] };
    const s = new DemoServer(f, () => 40);

    for (let i = 0; i < 400; i++) s.step();

    expect(s.snapshot.flows[0].agents.map((a) => a.id).sort()).toEqual(["DEMO-1", "DEMO-2"]);
    expect(s.snapshot.settled).toEqual({});
  });

  it("starts a returned card's lane path afresh, as a new task", () => {
    const f = fixture();
    f.flows = [{ name: "board", machine: { ...machine("new", [["new", "ready", "CREATE"], ["ready", "done", "FINISH"]], "done"), mainLine: ["new", "ready"] }, agents: [card("DEMO-2", "ready")] }];
    const s = new DemoServer(f, () => 40);

    s.step(() => 0);

    expect(lane(s, "DEMO-2")).toBe("ready");
    expect(s.lanes["DEMO-2"]).toEqual([{ at: 40, from: null, to: "ready" }]);
  });

  it("answers a route the demo cannot serve with why, not a network error", async () => {
    const s = new DemoServer(fixture());

    const reply = await s.fetch("/api/run/ops/nightly", { method: "POST" });

    expect(reply.status).toBe(404);
    expect((await reply.json()).error).toBe(ROUTES["/api/run"]);
  });

  it("refuses a session start with why, and names no harness, so the start question offers only Work it manually", async () => {
    const s = new DemoServer(fixture());
    const fetcher = (url: string, init?: RequestInit) => s.fetch(url, init);

    expect(await postStart("DEMO-1", "@agent-standard-high", fetcher)).toEqual({ ok: false, reason: ROUTES["/api/start"] });
    expect(await fetchHarnesses(fetcher)).toEqual(NO_HARNESSES);
  });
});

const sources = import.meta.glob<string>(["./*.ts", "./*.tsx", "!./*.test.ts"], { query: "?raw", import: "default", eager: true });

describe("the demo's route table", () => {
  it("covers every /api route the page requests, so a new route cannot quietly break the public demo", () => {
    const routes = new Set(Object.values(sources).flatMap((text) => [...text.matchAll(/["'`](\/api\/[a-z-]+)/g)].map((m) => m[1])));

    expect(routes.size).toBeGreaterThan(3);
    expect([...routes].filter((r) => !(r in ROUTES))).toEqual([]);
  });
});
