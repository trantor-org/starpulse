import { describe, expect, it, vi } from "vitest";
import { DemoServer, ROUTES, stepRuns, type DemoFixture } from "./demo";
import { NO_HARNESSES, fetchHarnesses, postStart } from "./start";
import type { Machine, RawAgent, RunStatus, Snapshot } from "./types";
import type { TaskRecord } from "./taskView";

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
  it("serves and edits a synthetic full task record so the public preview exercises edit mode", async () => {
    const s = new DemoServer(fixture());
    const opened = await body(s.fetch("/api/task/DEMO-1")) as { record: TaskRecord };
    const reply = await s.fetch("/api/edit", { method: "POST", body: JSON.stringify({
      task: "DEMO-1", base: { title: opened.record.title }, changes: { title: "Edited in the demo" }, comment: "proof",
    }) });

    expect(reply.status).toBe(200);
    expect(await reply.json()).toEqual({ task: "DEMO-1", changed: ["title"] });
    expect((await body(s.fetch("/api/task/DEMO-1"))).record.title).toBe("Edited in the demo");
    expect(s.snapshot.capabilities?.edit).toBe(true);
    expect(s.snapshot.flows[0].agents[0].title).toBe("Edited in the demo");
  });

  it("can render the writer-refusal state in a public review fixture", async () => {
    const s = new DemoServer(fixture(), undefined, true);
    const opened = await body(s.fetch("/api/task/DEMO-1")) as { record: TaskRecord };
    const reply = await s.fetch("/api/edit", { method: "POST", body: JSON.stringify({
      task: "DEMO-1", base: { title: opened.record.title }, changes: { title: "Refused edit" },
    }) });

    expect(reply.status).toBe(409);
    expect(await reply.json()).toEqual({ error: "The demo writer refused this edit.", skill: "completing-tasks" });
    expect((await body(s.fetch("/api/task/DEMO-1"))).record.title).toBe(opened.record.title);
  });

  it("archives a synthetic task so the public preview exercises the archive confirm", async () => {
    const s = new DemoServer(fixture());
    const reply = await s.fetch("/api/archive", { method: "POST", body: JSON.stringify({ task: "DEMO-1", reason: "superseded" }) });

    expect(s.snapshot.capabilities?.archive).toBe(true);
    expect(reply.status).toBe(200);
    expect(await reply.json()).toEqual({ task: "DEMO-1" });
    expect(lane(s, "DEMO-1")).toBeUndefined();
    expect((await s.fetch("/api/task/DEMO-1")).status).toBe(404);
  });

  it("can render the archive-refusal state in a public review fixture", async () => {
    const s = new DemoServer(fixture(), undefined, true);
    const reply = await s.fetch("/api/archive", { method: "POST", body: JSON.stringify({ task: "DEMO-1", reason: "" }) });

    expect(reply.status).toBe(409);
    expect(await reply.json()).toEqual({ error: "The demo writer refused this archive; the task was not archived.", skill: "completing-tasks" });
    expect(lane(s, "DEMO-1")).toBe("in_progress");
  });

  it("refuses an archive of a task that is not on the board", async () => {
    const reply = await new DemoServer(fixture()).fetch("/api/archive", { method: "POST", body: JSON.stringify({ task: "DEMO-9", reason: "" }) });

    expect(reply.status).toBe(404);
  });

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

  it("keeps its Board full: a card the walk settles stays settled now, and new work created now takes its place in the first lane", () => {
    const f = fixture();
    f.flows[0].machine = { ...BOARD, mainLine: ["new", "ready", "in_progress", "review", "done"] };
    const s = new DemoServer(f, () => 40);

    for (let i = 0; i < 400; i++) s.step();

    const settled = Object.values(s.snapshot.settled), cards = s.snapshot.flows[0].agents;
    expect(settled.length).toBeGreaterThan(0);
    expect(cards).toHaveLength(2);
    expect(settled.every((e) => e.state === "completed" && e.at === 40)).toBe(true);
    expect(cards.filter((a) => !["DEMO-1", "DEMO-2"].includes(a.id)).every((a) => a.created === 40 && s.records[a.id])).toBe(true);
  });

  it("starts the new work's lane path afresh, as a new task", () => {
    const f = fixture();
    f.flows = [{ name: "board", machine: { ...machine("new", [["new", "ready", "CREATE"], ["ready", "done", "FINISH"]], "done"), mainLine: ["new", "ready"] }, agents: [card("DEMO-2", "ready")] }];
    const s = new DemoServer(f, () => 40);

    s.step(() => 0);

    expect(s.snapshot.settled["DEMO-2"]).toMatchObject({ state: "done", at: 40, title: "DEMO-2" });
    expect(s.snapshot.flows[0].agents.map((a) => [a.id, a.state])).toEqual([["DEMO-3", "ready"]]);
    expect(s.lanes["DEMO-3"]).toEqual([{ at: 40, from: null, to: "ready" }]);
  });

  it("keeps the fixture's times as ages, so a task settled an hour before the capture settled an hour before the page opened", () => {
    const f = fixture();
    f.flows[0].agents[1].created = 50;
    f.settled = { "DEMO-9": { state: "completed", at: 40, created: 10, title: "shipped", model: "" } };

    const s = new DemoServer(f, () => 1000);

    expect(s.snapshot.flows[0].agents.map((a) => a.created)).toEqual([undefined, 950]);
    expect(s.snapshot.settled["DEMO-9"]).toMatchObject({ at: 940, created: 910 });
  });

  it("answers a route the demo cannot serve with why, not a network error", async () => {
    const s = new DemoServer(fixture());

    const reply = await s.fetch("/api/run/ops/nightly", { method: "POST" });

    expect(reply.status).toBe(404);
    expect((await reply.json()).error).toBe(ROUTES["/api/run"]);
  });

  it("answers /api/forwarding with the board's moves as the forwarder would cut them, and flips the names with the opt-in", async () => {
    const s = new DemoServer(fixture(), () => 100);
    const put = (optIn: unknown) => body(s.fetch("/api/forwarding", { method: "PUT", body: JSON.stringify({ opt_in: optIn }) }));

    const listed = await body(s.fetch("/api/forwarding"));

    expect(listed).toMatchObject({ configured: true, optIn: false, names: false, refused: false, problem: null });
    expect(listed.next.map((r: { fields: { task: string } }) => r.fields.task)).toEqual(["DEMO-1", "DEMO-2"]);
    expect(listed.next.every((r: { fields: object }) => !("actor" in r.fields))).toBe(true);
    expect(listed.contract["machine:events"].filter((f: { person: boolean }) => f.person).map((f: { field: string }) => f.field)).toEqual(["actor", "assignee"]);

    const named = await put(true);
    expect(named).toMatchObject({ optIn: true, names: true });
    expect(named.next.every((r: { fields: { actor?: string } }) => typeof r.fields.actor === "string")).toBe(true);
    expect((await put(false)).next.every((r: { fields: object }) => !("actor" in r.fields))).toBe(true);
  });

  it("names its stand-in hub without a URL, which the demo publisher refuses in a public page", async () => {
    const listed = await new DemoServer(fixture(), () => 100).fetch("/api/forwarding").then((r) => r.json());

    expect(JSON.stringify(listed)).not.toMatch(/https?:\/\//);
  });

  it("refuses an opt-in that is not a boolean, as the server does", async () => {
    const s = new DemoServer(fixture());

    const reply = await s.fetch("/api/forwarding", { method: "PUT", body: JSON.stringify({ opt_in: "yes" }) });

    expect(reply.status).toBe(400);
  });

  it("can stand in for a hub that refuses names, a hub that is down, and an instance that forwards nothing", async () => {
    const refused = new DemoServer(fixture(), () => 100, false, "refused");
    const down = new DemoServer(fixture(), () => 100, false, "down");
    const none = new DemoServer(fixture(), () => 100, false, "none");
    const optIn = { method: "PUT", body: JSON.stringify({ opt_in: true }) };

    expect(await body(refused.fetch("/api/forwarding", optIn))).toMatchObject({ optIn: true, names: false, refused: true });
    expect(await body(down.fetch("/api/forwarding"))).toMatchObject({ lastSent: null, problem: expect.stringContaining("unreachable") });
    expect(await body(none.fetch("/api/forwarding"))).toEqual({ configured: false });
    expect((await none.fetch("/api/forwarding", optIn)).status).toBe(404);
  });

  it("creates a task in the first lane, as the served board does, and says so in its snapshot", async () => {
    const s = new DemoServer(fixture());
    const reply = await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "Write the docs" }) });

    expect(s.snapshot.capabilities?.create).toBe(true);
    expect(reply.status).toBe(201);
    expect(await reply.json()).toEqual({ task: "DEMO-3" });
    expect(s.snapshot.flows[0].agents.find((a) => a.id === "DEMO-3")).toMatchObject({ title: "Write the docs", state: "ready" });
    expect((await body(s.fetch("/api/task/DEMO-3"))).record.title).toBe("Write the docs");
  });

  it("numbers a created task past the settled ones, so it never reuses a settled task's id", async () => {
    const f = fixture();
    f.settled = { "DEMO-9": { state: "completed", at: 40, created: 10, title: "shipped", model: "" } };
    const s = new DemoServer(f);

    const reply = await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "Write the docs" }) });

    expect(await reply.json()).toEqual({ task: "DEMO-10" });
  });

  it("creates a task with every detail the form filled, on its card and in its record", async () => {
    const s = new DemoServer(fixture());
    const details = { description: "Every lane", priority: "High", labels: ["docs"], milestone: "m-1", assignee: "@agent-fast-low", dependencies: ["DEMO-1"], acceptanceCriteria: ["Names every lane"] };
    await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "Write the docs", ...details }) });

    expect(s.snapshot.flows[0].agents.find((a) => a.id === "DEMO-3")).toMatchObject({ model: "@agent-fast-low", labels: ["docs"], milestone: "m-1", dependencies: ["DEMO-1"], description: "Every lane" });
    expect((await body(s.fetch("/api/task/DEMO-3"))).record).toMatchObject({
      profile: "@agent-fast-low", priority: "High", labels: ["docs"], milestone: "m-1", dependencies: ["DEMO-1"], description: "Every lane",
      acceptanceCriteria: [{ n: 1, text: "Names every lane", checked: false }],
    });
  });

  it("creates a task in the board's starting lane, not its first working lane", async () => {
    const f = fixture();
    const native = { ...machine("to_do", [["to_do", "in_progress", "START"], ["in_progress", "done", "FINISH"]], "done"), mainLine: ["to_do", "in_progress", "done"] };
    f.flows = [{ name: "board", machine: native, agents: [card("DEMO-1", "in_progress")] }];
    const s = new DemoServer(f);
    await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "Write the docs" }) });

    expect(s.snapshot.flows[0].agents.find((a) => a.id === "DEMO-2")?.state).toBe("to_do");
  });

  it("leaves a task the viewer created in its starting lane while the demo walks, until the viewer moves it", async () => {
    const f = fixture();
    f.flows = [{ name: "board", machine: { ...machine("to_do", [["to_do", "in_progress", "START"], ["in_progress", "done", "FINISH"]], "done"), mainLine: ["to_do", "in_progress", "done"] }, agents: [] }];
    const s = new DemoServer(f);
    const { task } = await (await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "Write the docs" }) })).json();
    for (let i = 0; i < 5; i++) s.step(() => 0);

    expect(s.snapshot.flows[0].agents.find((a) => a.id === task)?.state).toBe("to_do");
    expect((await s.fetch("/api/move", { method: "POST", body: JSON.stringify({ task, to: "in_progress" }) })).status).toBe(200);
    expect(s.snapshot.flows[0].agents.find((a) => a.id === task)?.state).toBe("in_progress");
  });

  it("refuses a create with no title, and a create the review fixture makes the writer refuse", async () => {
    const s = new DemoServer(fixture(), undefined, true);

    expect((await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: " " }) })).status).toBe(400);
    const refused = await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "x" }) });
    expect(refused.status).toBe(409);
    expect((await refused.json()).error).toContain("task was not created");
    expect(s.snapshot.flows[0].agents.map((a) => a.id)).toEqual(["DEMO-1", "DEMO-2"]);
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

const STEPS = ["refuse", "lint", "wait_ci", "ready"];
const run = (runId: string, step: string) => ({
  runId, status: "running" as const, startedAt: "2026-10-05T16:00:00Z", step, stepStartedAt: "2026-10-05T16:00:05Z",
  steps: Object.fromEntries(STEPS.map((n, i) => [n, i < STEPS.indexOf(step) ? "succeeded" : i === STEPS.indexOf(step) ? "running" : "not_started"])) as Record<string, RunStatus>,
});
const fan = (...at: string[]): Snapshot => ({
  ...fixture(),
  dags: [{
    name: "dagu/deliver", status: "running", runId: "deliver-agent-demo-1", startedAt: "", finishedAt: "", pool: "dagu/deliver",
    steps: STEPS.map((name, i) => ({ name, depends: i ? [STEPS[i - 1]] : [], status: "not_started" as const })),
    active: at.map((step, i) => run(`deliver-agent-demo-${i + 1}`, step)),
  }],
  pools: [{ name: "dagu/deliver", cap: 2, running: at.length, queued: 0 }],
});
const script = (...v: number[]) => () => v.shift() ?? 0;

describe("the demo's fan-out", () => {
  it("moves a run in flight to its next step, marking the one it left done", () => {
    const next = stepRuns(fan("lint", "wait_ci"), script(0.1, 0, 0));

    const [moved, other] = next.dags[0].active!;
    expect(moved).toMatchObject({ step: "wait_ci", steps: { refuse: "succeeded", lint: "succeeded", wait_ci: "running", ready: "not_started" } });
    expect(moved.stepStartedAt).not.toBe("2026-10-05T16:00:05Z");
    expect(other.step).toBe("wait_ci");
    expect(next.pools).toEqual([{ name: "dagu/deliver", cap: 2, running: 2, queued: 0 }]);
  });

  it("ends a run in its last step, freeing its slot in the pool", () => {
    const next = stepRuns(fan("ready", "lint"), script(0.1, 0, 0));

    expect(next.dags[0].active!.map((r) => r.step)).toEqual(["lint"]);
    expect(next.dags[0].status).toBe("running");
    expect(next.pools).toEqual([{ name: "dagu/deliver", cap: 2, running: 1, queued: 0 }]);
  });

  it("settles the DAG once its last run ends", () => {
    const next = stepRuns(fan("ready"), script(0.1, 0, 0));

    expect(next.dags[0]).toMatchObject({ status: "succeeded", active: [] });
    expect(next.dags[0].finishedAt).not.toBe("");
    expect(next.pools![0].running).toBe(0);
  });

  it("starts a new run in the first step while the pool has room", () => {
    const next = stepRuns(fan("lint"), script(0.6, 0));

    const [, started] = next.dags[0].active!;
    expect(started).toMatchObject({ status: "running", step: "refuse", steps: { refuse: "running", lint: "not_started" } });
    expect(started.runId).toMatch(/^deliver-agent-demo-\d+$/);
    expect(next.pools![0].running).toBe(2);
  });

  it("starts nothing once the pool is full", () => {
    const next = stepRuns(fan("lint", "wait_ci"), script(0.6, 0));

    expect(next.dags[0].active).toHaveLength(2);
    expect(next.pools![0]).toMatchObject({ running: 2, queued: 0 });
  });

  it("leaves a snapshot with no pools or runs as it was", () => {
    const snap = { ...fixture(), dags: [{ name: "x", status: "succeeded" as const, runId: "", startedAt: "", finishedAt: "", steps: [] }] };

    expect(stepRuns(snap, script(0.1, 0, 0))).toEqual(snap);
  });

  it("is what the embedded server plays on each step", () => {
    const s = new DemoServer({ ...fan("lint", "wait_ci"), history: {} });

    s.step(script(0.1, 0, 0, 0, 0, 0, 0, 0, 0));

    expect(s.snapshot.dags[0].active!.map((r) => r.step)).toEqual(["wait_ci", "wait_ci"]);
  });
});
