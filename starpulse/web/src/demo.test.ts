import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoServer, ROUTES, demoLive, stepRuns, type DemoFixture } from "./demo";
import { PAGE } from "./ledgerScroll";
import { NO_HARNESSES, fetchHarnesses, postStart } from "./start";
import type { FlowSnapshot, LedgerRow, Machine, RawAgent, RunStatus, Snapshot } from "./api";
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

/** The fixture with a DAG that writes MERGED and one cued by it, so its Board has a Ledger. */
function tied(): DemoFixture {
  const f = fixture(), steps = (names: string[]) => names.map((n, i) => ({ name: n, depends: i ? [names[i - 1]] : [], status: "succeeded" as RunStatus, kind: null }));
  f.flows[0].machine = { ...BOARD, writers: { MERGED: [{ actor: "main-follow", trigger: "push" }] }, dagActors: ["main-follow"] };
  f.cues = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge", resolves: "forced" }];
  f.dags = ["main-follow", "apply-on-merge"].map((name) => ({ name, status: "succeeded" as RunStatus, runId: "r", startedAt: "", finishedAt: "", steps: steps(["a", "b"]) }));
  return f;
}

describe("the demo server's contract report", () => {
  afterEach(() => vi.unstubAllGlobals());
  const report = async (ms: string) => {
    vi.stubGlobal("location", { search: `?ms=${ms}` });
    return body(new DemoServer(tied(), () => 1000).fetch("/api/doctor"));
  };

  it("answers the shape GET /api/doctor serves: a check for each cued DAG, all passing where runs are keyed by commit", async () => {
    const live = await report("live");

    expect(live).toEqual({ ok: true, checks: [{ check: "cue:apply-on-merge", status: "pass", reason: expect.stringContaining("apply-on-merge") }] });
    expect((await report("fail")).checks.map((c: { status: string }) => c.status)).toEqual(["pass"]);
  });

  it("warns, without failing, that the infer scenario declares no commit key", async () => {
    const infer = await report("infer");

    expect(infer.ok).toBe(true);
    expect(infer.checks).toEqual([{ check: "cue:apply-on-merge", status: "warn", reason: expect.stringContaining("[runs.commit] after key") }]);
  });
});

describe("the demo server's 24-hour strip and forced reruns", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });
  const failing = () => {
    vi.stubGlobal("location", { search: "?ms=fail" });
    return new DemoServer(tied(), () => 1000);
  };
  const post = (s: DemoServer, dag: string) => s.fetch(`/api/runs/${dag}/rerun`, { method: "POST" });

  it("sends the day's merges bucketed by quarter-hour with the snapshot, and the pins the newest page leaves out", () => {
    const s = failing(), snap = s.snapshot;

    expect(snap.mergeStrip!.buckets).toHaveLength(96);
    expect(snap.mergeStrip!.buckets.reduce((n, b) => n + b.merges, 0)).toBeGreaterThan(60);
    expect(snap.mergeStrip!.buckets.reduce((n, b) => n + b.failed, 0)).toBe(2);
    const head = new Set(snap.ledgers!.MERGED.map((r) => r.key));
    expect(snap.mergePins!.length).toBe(1);
    expect(snap.mergePins!.every((r) => r.pinned && !head.has(r.key))).toBe(true);
  });

  it("starts a forced run for a DAG with an unresolved failure, then clears the failures it was a rerun of", async () => {
    vi.useFakeTimers();
    const s = failing(), seen: Snapshot[] = [];
    s.subscribe((snap) => seen.push(snap));

    const reply = await post(s, "apply-on-merge"), { runId } = await reply.json();

    expect(reply.status).toBe(200);
    expect(s.snapshot.dags.find((d) => d.name === "apply-on-merge")!.active!.map((r) => r.runId)).toEqual([runId]);
    vi.advanceTimersByTime(5000);
    expect(s.snapshot.dags.find((d) => d.name === "apply-on-merge")!.active ?? []).toEqual([]);
    expect(s.snapshot.ledgers!.MERGED.flatMap((r) => Object.values(r.fails)).every((f) => f.resolved?.runId === runId)).toBe(true);
    expect(s.snapshot.mergePins).toEqual([]);
  });

  it("refuses a rerun with no unresolved failure, or while one is already running, saying why", async () => {
    vi.useFakeTimers();
    const s = failing();

    const none = await post(s, "main-follow");
    await post(s, "apply-on-merge");
    const busy = await post(s, "apply-on-merge");

    expect([none.status, (await none.json()).error]).toEqual([409, "main-follow has no unresolved failure to rerun."]);
    expect([busy.status, (await busy.json()).error]).toEqual([409, "apply-on-merge already has a forced rerun running."]);
  });
});

describe("the page's snapshot in a demo", () => {
  it("keeps its own machines and takes the server's workflows and Ledger, so a forced rerun's resolution reaches the page", () => {
    const own = new DemoServer(tied(), () => 1000).snapshot, served = structuredClone(own);
    served.dags = [];
    served.ledgers = { MERGED: [] };
    served.mergeStrip = { since: 1, bucket: 900, buckets: [] };
    served.mergePins = [];
    served.flows = [];

    const live = demoLive(own, served);

    expect([live.dags, live.ledgers, live.mergeStrip, live.mergePins]).toEqual([[], { MERGED: [] }, served.mergeStrip, []]);
    expect(live.flows).toBe(own.flows);
  });
});

describe("the demo server's Ledger", () => {
  it("holds merge rows only when a DAG is tied to the merge", () => {
    expect(new DemoServer(fixture()).snapshot.ledgers).toBeUndefined();
    expect(new DemoServer(tied(), () => 1000).snapshot.ledgers?.MERGED.length).toBeGreaterThan(5);
  });

  it("sends only the newest page as the snapshot's head, as the server does", () => {
    expect(new DemoServer(tied(), () => 1000).snapshot.ledgers!.MERGED).toHaveLength(PAGE);
  });

  it("lands a new merge on top and tells its listeners, the runs in flight finishing, the head staying a page", () => {
    const s = new DemoServer(tied(), () => 1000), seen: number[] = [];
    s.subscribe((snap) => seen.push(snap.ledgers!.MERGED.length));

    s.land();

    expect(seen).toEqual([PAGE]);
    expect(s.snapshot.ledgers!.MERGED[0].runs["main-follow"].status).toBe("running");
    expect(s.snapshot.ledgers!.MERGED[1].runs["apply-on-merge"].status).toBe("succeeded");
  });

  it("serves the older merges a page at a time from /api/merges, newest first and none twice, to the end of the day", async () => {
    const s = new DemoServer(tied(), () => 1000), head = s.snapshot.ledgers!.MERGED, got: LedgerRow[] = [];
    let before = head.at(-1)!.at, more = true;

    while (more) {
      const reply = await s.fetch(`/api/merges?before=${before}&limit=${PAGE}`), body = (await reply.json()) as { merges: LedgerRow[]; more: boolean };
      expect(body.merges.length).toBeLessThanOrEqual(PAGE);
      got.push(...body.merges);
      more = body.more && body.merges.length > 0;
      before = body.merges.at(-1)?.at ?? before;
    }

    const all = [...head, ...got];
    expect(all.length).toBeGreaterThan(60);
    expect(new Set(all.map((r) => r.key)).size).toBe(all.length);
    expect(all.map((r) => r.at)).toEqual([...all.map((r) => r.at)].sort((a, b) => b - a));
  });

  it("keeps the older merges after a merge lands, the head sliding forward by one", async () => {
    const s = new DemoServer(tied(), () => 1000), first = s.snapshot.ledgers!.MERGED;
    s.land();
    const head = s.snapshot.ledgers!.MERGED, body = (await (await s.fetch(`/api/merges?before=${head.at(-1)!.at}&limit=${PAGE}`)).json()) as { merges: LedgerRow[] };

    expect(head.slice(1).map((r) => r.key)).toEqual(first.slice(0, PAGE - 1).map((r) => r.key));
    expect(body.merges[0].key).toBe(first.at(-1)!.key);
  });

  it("has no merge to land without a Ledger", () => {
    const s = new DemoServer(fixture()), seen: Snapshot[] = [];
    s.subscribe((snap) => seen.push(snap));

    s.land();

    expect(seen).toEqual([]);
  });
});

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
    steps: STEPS.map((name, i) => ({ name, depends: i ? [STEPS[i - 1]] : [], status: "not_started" as const, kind: null })),
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

describe("the demo server's /api/machines", () => {
  /** The fixture with 45 machines entered from the In Progress one, each a minute older than the one before and the last three sharing a time. */
  function crowded(): DemoFixture {
    const f = fixture();
    f.flows[1] = { ...f.flows[1], parent: null, depth: 0, last: 100 };
    f.flows.push(...Array.from({ length: 45 }, (_, i) => ({ name: `kid${i}`, machine: DELIVERY, agents: [], parent: "in-progress", depth: 1, last: i >= 42 ? 10 : 100 - i * 2 })));
    return f;
  }
  const page = (s: DemoServer, q: string) => body(s.fetch(`/api/machines?${q}`)) as Promise<{ open: string; machines: { name: string; last: number }[]; more: boolean }>;

  it("serves the machines older than `before`, newest first, 20 at a time, ties travelling together, with no row twice", async () => {
    const s = new DemoServer(crowded(), () => 100);
    const seen: string[] = [];
    let before = "", more = true, calls = 0;
    while (more && calls++ < 10) {
      const p = await page(s, `open=in-progress&limit=20${before}`);
      seen.push(...p.machines.map((m) => m.name));
      more = p.more;
      before = `&before=${Math.min(...p.machines.map((m) => m.last))}`;
    }
    expect(seen).toEqual(Array.from({ length: 45 }, (_, i) => `kid${i}`));
    expect(calls).toBe(3);
    expect(more).toBe(false);
  });

  it("names the machine it opened, and refuses one the demo does not have", async () => {
    const s = new DemoServer(crowded(), () => 100);
    expect((await page(s, "limit=5")).open).toBe("in-progress");
    expect((await s.fetch("/api/machines?open=nope")).status).toBe(404);
  });

  it("keeps the machines' activity and the strip's entries as ages, so a fixture captured an hour before the page opened is an hour old", () => {
    const f = crowded();
    f.machineStrip = { entries: [{ at: 90, machine: "kid0", row: "kid0", from: null, dag: null }] };
    const s = new DemoServer(f, () => 200); // the fixture was captured at 100
    expect(s.snapshot.flows.find((x) => x.name === "kid0")?.last).toBe(200);
    expect(s.snapshot.machineStrip?.entries[0].at).toBe(190);
  });
});

describe("a demo page asked for many machines", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("serves the machines padded to the count, a page at a time", async () => {
    const base = fixture(), kid: FlowSnapshot = { name: "docs", machine: DELIVERY, agents: [], parent: "in-progress", depth: 1, chain: [], nested: [], ties: [], last: base.now - 60, stuck: null };
    const fx = { ...base, flows: [...base.flows, kid], machinePage: { open: "in-progress", machines: ["docs"], more: false } };
    vi.stubGlobal("location", { search: "?demo&many=45" });
    vi.stubGlobal("__FLOW_FIXTURE__", fx);
    vi.resetModules();
    const { demoServer } = await import("./demo");
    const first = (await (await demoServer()!.fetch("/api/machines?open=in-progress&limit=20")).json()) as { machines: unknown[]; more: boolean };
    expect(first.machines).toHaveLength(20);
    expect(first.more).toBe(true);
  });
});
