import { afterEach, describe, expect, it, vi } from "vitest";
import { DemoServer, ROUTES, demoLive, demoStep, stepRuns, type DemoFixture } from "./demo";
import { PAGE } from "../features/level/ledgerScroll";
import { fetchHarnesses, postStart } from "../features/kanban/start";
import type { FlowSnapshot, LedgerRow, Machine, RawTask, RunStatus, Snapshot } from "../api";
import type { TaskRecord } from "../features/kanban/taskViewModel";
import { LIFECYCLE_ROLES } from "../tests/lifecycleRoles";

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
const card = (id: string, state: string): RawTask => ({ id, title: id, state, model: "" });
/** A page of the merge Ledger as `GET /api/ledger/MERGED` serves it: the newest, or the rows older than `before`. */
const ledgerPage = async (s: DemoServer, before?: number) => (await (await s.fetch(`/api/ledger/MERGED?${before === undefined ? "" : `before=${before}&`}limit=${PAGE}`)).json()) as { rows: LedgerRow[]; more: boolean };

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
    roles: LIFECYCLE_ROLES,
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
  const f = fixture(), steps = (names: string[]) => names.map((n, i) => ({ name: n, depends: i ? [names[i - 1]] : [], status: "succeeded" as RunStatus, kind: null, precondition: null, lock: null, last: [] as [] }));
  f.flows[0].machine = { ...BOARD, writers: { MERGED: [{ actor: "main-follow", trigger: "push" }] }, dagActors: ["main-follow"] };
  f.cues = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge", resolves: "forced" }];
  f.dags = ["main-follow", "apply-on-merge"].map((name) => ({ name, status: "succeeded" as RunStatus, runId: "r", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: steps(["a", "b"]) }));
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

  it("sends the day's merges bucketed by quarter-hour with the snapshot, and the pins the newest page leaves out", async () => {
    const s = failing(), snap = s.snapshot;

    expect(snap.mergeStrip!.buckets).toHaveLength(96);
    expect(snap.mergeStrip!.buckets.reduce((n, b) => n + b.merges, 0)).toBeGreaterThan(60);
    expect(snap.mergeStrip!.buckets.reduce((n, b) => n + b.failed, 0)).toBe(2);
    const head = new Set((await ledgerPage(s)).rows.map((r) => r.key));
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
    expect((await ledgerPage(s)).rows.flatMap((r) => Object.values(r.fails)).every((f) => f.resolved?.runId === runId)).toBe(true);
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
  it("keeps its own machines and takes the server's workflows and Ledger strip and pins, so a forced rerun's resolution reaches the page", () => {
    const own = new DemoServer(tied(), () => 1000).snapshot, served = structuredClone(own);
    served.dags = [];
    served.mergeStrip = { since: 1, bucket: 900, buckets: [] };
    served.mergePins = [];
    served.flows = [];

    const live = demoLive(own, served);

    expect([live.dags, live.mergeStrip, live.mergePins]).toEqual([[], served.mergeStrip, []]);
    expect(live.flows).toBe(own.flows);
  });
});

describe("the demo server's Ledger", () => {
  it("holds merge rows only when a DAG is tied to the merge", async () => {
    const bare = new DemoServer(fixture()), tiedTo = new DemoServer(tied(), () => 1000);

    expect([bare.snapshot.mergeStrip, (await ledgerPage(bare)).rows]).toEqual([undefined, []]);
    expect((await ledgerPage(tiedTo)).rows.length).toBeGreaterThan(5);
  });

  it("sends no ledger rows with the snapshot, as the server does", () => {
    expect(new DemoServer(tied(), () => 1000).snapshot).not.toHaveProperty("ledgers");
  });

  it("serves the newest page of rows, as the server does", async () => {
    expect((await ledgerPage(new DemoServer(tied(), () => 1000))).rows).toHaveLength(PAGE);
  });

  it("lands a new merge on top and tells its listeners, the runs in flight finishing, the head staying a page", async () => {
    const s = new DemoServer(tied(), () => 1000), seen: Snapshot[] = [];
    s.subscribe((snap) => seen.push(snap));

    s.land();
    const { rows } = await ledgerPage(s);

    expect(seen).toHaveLength(1);
    expect(rows).toHaveLength(PAGE);
    expect(rows[0].runs["main-follow"].status).toBe("running");
    expect(rows[1].runs["apply-on-merge"].status).toBe("succeeded");
  });

  it("serves the older merges a page at a time from /api/ledger/MERGED, newest first and none twice, to the end of the day", async () => {
    const s = new DemoServer(tied(), () => 1000), head = (await ledgerPage(s)).rows, got: LedgerRow[] = [];
    let before = head.at(-1)!.at, more = true;

    while (more) {
      const body = await ledgerPage(s, before);
      expect(body.rows.length).toBeLessThanOrEqual(PAGE);
      got.push(...body.rows);
      more = body.more && body.rows.length > 0;
      before = body.rows.at(-1)?.at ?? before;
    }

    const all = [...head, ...got];
    expect(all.length).toBeGreaterThan(60);
    expect(new Set(all.map((r) => r.key)).size).toBe(all.length);
    expect(all.map((r) => r.at)).toEqual([...all.map((r) => r.at)].sort((a, b) => b - a));
  });

  it("keeps the older merges after a merge lands, the head sliding forward by one", async () => {
    const s = new DemoServer(tied(), () => 1000), first = (await ledgerPage(s)).rows;
    s.land();
    const head = (await ledgerPage(s)).rows, body = await ledgerPage(s, head.at(-1)!.at);

    expect(head.slice(1).map((r) => r.key)).toEqual(first.slice(0, PAGE - 1).map((r) => r.key));
    expect(body.rows[0].key).toBe(first.at(-1)!.key);
  });

  it("has no rows for an event the demo does not hold", async () => {
    expect(await (await new DemoServer(tied(), () => 1000).fetch("/api/ledger/CLAIM?limit=20")).json()).toEqual({ rows: [], more: false });
  });

  it("has no merge to land without a Ledger", () => {
    const s = new DemoServer(fixture()), seen: Snapshot[] = [];
    s.subscribe((snap) => seen.push(snap));

    s.land();

    expect(seen).toEqual([]);
  });
});

describe("the demo server", () => {
  it("gives a synthetic session link to the record of each In Progress card only", async () => {
    const s = new DemoServer(fixture());
    const cards = s.snapshot.flows.find((f) => f.name === "board")!.agents;
    const sessions = await Promise.all(cards.map(async (a) => [a.state, ((await body(s.fetch(`/api/task/${a.id}`))).record as TaskRecord).session] as const));

    expect(sessions.some(([state]) => state === "in_progress")).toBe(true);
    for (const [state, session] of sessions) expect(session).toEqual(state === "in_progress" ? expect.stringMatching(/^#demo-session-\d+$/) : "");
  });

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

  it("gives a seeded task a Markdown body the dialog draws or hides, and an unassigned one no plan", async () => {
    const seeded = { ...fixture(), flows: [{ name: "board", machine: BOARD, agents: [{ ...card("DEMO-1", "ready"), model: "@agent-fast-low" }, card("DEMO-2", "new")] }] };
    const s = new DemoServer(seeded);
    const read = async (id: string) => (await body(s.fetch(`/api/task/${id}`))).record as TaskRecord;
    const one = await read("DEMO-1");

    expect(one.description).toContain("| Stage | Hosts | Window |");
    expect(one.description).toContain("```\nstarpulse task list --status ready\n```");
    for (const section of ["Duplicate Search", "Duplicate Resolution", "ADR Needed"]) expect(one.description).toContain(`## ${section}`);
    expect(one.notes).toMatch(/^\*\*Assignee:\*\* @agent-fast-low\n/);
    expect(one.plan).not.toBe("");
    expect((await read("DEMO-2")).plan).toBe("");
  });

  it("gives a Waiting task Start Criteria, and with a failing evaluator one it could not read", async () => {
    const waiting = { ...fixture(), flows: [{ name: "board", machine: BOARD, agents: [card("DEMO-4", "waiting"), card("DEMO-2", "ready")] }] };
    const read = async (s: DemoServer, id: string) => (await body(s.fetch(`/api/task/${id}`))).record as TaskRecord;
    const ok = new DemoServer(waiting, () => 1000);
    const four = await read(ok, "DEMO-4");

    expect(four.start_criteria?.map((c) => c.status)).toEqual(["met", "unmet", "unmet"]);
    expect(four.start_criteria?.find((c) => c.expr === "time()")).toMatchObject({ cmp: "at_least", want: 1000 + 3600 * 5 });
    expect(four.description).toContain("start_criteria:");
    expect((await read(ok, "DEMO-2")).start_criteria).toBeUndefined();

    const failing = await read(new DemoServer(waiting, () => 1000, false, true), "DEMO-4");
    expect(failing.start_criteria?.map((c) => c.status)).toEqual(["met", "error"]);
    expect(failing.start_criteria?.[1].error).toContain("prometheus");
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

  it("keeps a rating on the snapshot, counting each change, so the public preview can rate a card", async () => {
    const s = new DemoServer(fixture());
    const rate = (verdict: string, reason = "") => s.fetch("/api/rating", { method: "POST", body: JSON.stringify({ task: "DEMO-1", verdict, reason, actor: "operator" }) });

    expect(await (await rate("pass")).json()).toEqual({ task: "DEMO-1", verdict: "pass", reason: "", changes: 1 });
    expect(await (await rate("fail", "drops the lane filter")).json()).toMatchObject({ verdict: "fail", changes: 2 });
    expect(s.snapshot.ratings?.["DEMO-1"]).toMatchObject({ verdict: "fail", reason: "drops the lane filter", actor: "operator", changes: 2 });
  });

  it("refuses a rating in the refusal fixture and for a task that is not on the board", async () => {
    const send = (s: DemoServer, task: string) => s.fetch("/api/rating", { method: "POST", body: JSON.stringify({ task, verdict: "pass" }) });
    const refusing = new DemoServer(fixture(), undefined, true);

    expect((await send(refusing, "DEMO-1")).status).toBe(503);
    expect(refusing.snapshot.ratings?.["DEMO-1"]).toBeUndefined();
    expect((await send(new DemoServer(fixture()), "DEMO-9")).status).toBe(404);
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

    expect(await body(s.fetch("/api/history?task=DEMO-1&machine=in-progress"))).toEqual({
      task: "DEMO-1",
      machine: "in-progress",
      path: [{ at: 50, event: "RED", state: "red" }],
      steps: 4,
    });
    expect((await s.fetch("/api/history?task=DEMO-1&machine=nowhere")).status).toBe(404);
  });

  it("answers a task's 24-hour replay as machine events from its trail on every machine", async () => {
    const s = new DemoServer(fixture());

    expect(await body(s.fetch("/api/history?task=DEMO-1&hours=24"))).toEqual({
      task: "DEMO-1",
      events: [{ at: 50, machine: "in-progress", event: "RED", from: "start", to: "red" }],
    });
    expect(await body(s.fetch("/api/history?task=DEMO-9&hours=24"))).toEqual({ task: "DEMO-9", events: [] });
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

  it("refuses to promote a proposal with no profile, as the served writer does, and promotes it once one is set", async () => {
    const proposing = machine("new", [["new", "proposed", "CREATE_PROPOSED"], ["proposed", "ready", "PROMOTE"], ["proposed", "archived", "DROP"]], "archived");
    const f = { ...fixture(), roles: { ...LIFECYCLE_ROLES, proposed: "proposed", ready: "ready" }, flows: [{ name: "board", machine: proposing, agents: [card("DEMO-7", "proposed"), card("DEMO-8", "proposed")] }] };
    const s = new DemoServer(f);
    const move = (task: string, to: string) => s.fetch("/api/move", { method: "POST", body: JSON.stringify({ task, to }) });

    const refused = await move("DEMO-7", "ready");

    expect(refused.status).toBe(409);
    expect((await refused.json()).error).toMatch(/DEMO-7.*no profile/);
    expect(lane(s, "DEMO-7")).toBe("proposed");
    const edit = await s.fetch("/api/edit", { method: "POST", body: JSON.stringify({ task: "DEMO-7", base: { profile: "" }, changes: { profile: "@agent-fast-low" } }) });
    expect(edit.status).toBe(200);
    expect((await move("DEMO-7", "ready")).status).toBe(200);
    expect(lane(s, "DEMO-7")).toBe("ready");
    expect((await move("DEMO-8", "completed")).status).toBe(200);
    expect(s.snapshot.flows[0].agents.map((a) => a.id)).toEqual(["DEMO-7"]);
  });

  it("records the lane change of every card its walk moves", () => {
    const s = new DemoServer(fixture(), () => 40);
    const before = new Map(s.snapshot.flows[0].agents.map((a) => [a.id, a.state]));

    for (let i = 0; i < 20; i++) s.step();

    for (const a of s.snapshot.flows[0].agents) {
      const path = s.lanes[a.id] ?? [];
      if (a.state !== before.get(a.id)) expect(path.at(-1)?.to).toBe(a.state); // by id: a settled card leaves the list and shifts the rest
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

  it("answers /api/scheduler with the board's sessions in flight and the pick the loop would admit next", async () => {
    const s = new DemoServer(fixture(), () => 1000);

    const status = await body(s.fetch("/api/scheduler"));

    expect(status).toMatchObject({ enabled: true, sampledAt: 1000 });
    expect(status.dimensions.map((d: { name: string }) => d.name)).toEqual(["cpu", "memory", "sessions", "review"]);
    expect(status.dimensions.find((d: { name: string }) => d.name === "sessions")).toMatchObject({ use: 1, limit: 4 });
    expect(status.inFlight).toMatchObject([{ task: "DEMO-1", title: "DEMO-1" }]);
    expect(status.next).toMatchObject({ task: "DEMO-2", verdict: "starting" });
  });

  it("flips the scheduler switch with a PUT, names no pick while it is off, and refuses a non-boolean", async () => {
    const s = new DemoServer(fixture(), () => 1000);
    const put = (enabled: unknown) => s.fetch("/api/scheduler", { method: "PUT", body: JSON.stringify({ enabled }) });

    const off = await body(put(false));
    const bad = await put("no");

    expect(off).toMatchObject({ enabled: false, next: null });
    expect(off.inFlight).toHaveLength(1);
    expect(bad.status).toBe(400);
    expect(await body(s.fetch("/api/scheduler"))).toMatchObject({ enabled: false });
  });

  it("overrides the selected harness's session cap with a PUT, drops it on null and refuses a non-whole number", async () => {
    const s = new DemoServer(fixture(), () => 1000);
    const put = (sessionCap: unknown) => s.fetch("/api/scheduler", { method: "PUT", body: JSON.stringify({ sessionCap }) });

    expect(await body(s.fetch("/api/scheduler"))).toMatchObject({ sessionCap: { harness: "claude", limit: 3, source: "starpulse.toml", configLimit: 3 } });
    expect(await body(put(8))).toMatchObject({ sessionCap: { limit: 8, source: "admin", configLimit: 3 }, sessionsByHarness: { claude: { limit: 8 } } });
    expect((await put(0)).status).toBe(400);
    expect((await put(2.5)).status).toBe(400);
    expect(await body(put(null))).toMatchObject({ sessionCap: { limit: 3, source: "starpulse.toml" } });
  });

  it("can stand in for a paused scheduler, a host over its limit, an empty queue, a refused switch and a server with no scheduler", async () => {
    const mode = (m: "off" | "over" | "empty" | "refused" | "down") => new DemoServer(fixture(), () => 1000, false, false, m);
    const turnOff = { method: "PUT", body: JSON.stringify({ enabled: false }) };

    expect(await body(mode("off").fetch("/api/scheduler"))).toMatchObject({ enabled: false });
    const over = await body(mode("over").fetch("/api/scheduler"));
    expect(over.next).toMatchObject({ task: "DEMO-2", verdict: "waits", reason: "RAM 91/85%" });
    expect(await body(mode("empty").fetch("/api/scheduler"))).toMatchObject({ enabled: true, next: null });
    const refused = mode("refused");
    expect((await refused.fetch("/api/scheduler", turnOff)).status).toBe(403);
    expect(await body(refused.fetch("/api/scheduler"))).toMatchObject({ enabled: true });
    const down = await mode("down").fetch("/api/scheduler");
    expect(down.status).toBe(404);
    expect((await down.json()).error).toContain("no scheduler");
  });

  it("keeps quiet hours with a PUT and, in its quiet state, holds the pick for them", async () => {
    const s = new DemoServer(fixture(), () => 1000);
    const put = (quietHours: unknown) => s.fetch("/api/scheduler", { method: "PUT", body: JSON.stringify({ quietHours }) });
    const night = { start: "22:00", end: "07:00", timezone: "America/Phoenix" };

    expect(await body(s.fetch("/api/scheduler"))).toMatchObject({ quietHours: null });
    expect(await body(put(night))).toMatchObject({ enabled: true, quietHours: night });
    expect(await body(put(null))).toMatchObject({ quietHours: null });
    expect((await put({ start: "22:00", end: "22:00", timezone: "UTC" })).status).toBe(400);
    const quiet = await body(new DemoServer(fixture(), () => 1000, false, false, "quiet").fetch("/api/scheduler"));
    expect(quiet).toMatchObject({ quietHours: { start: "22:00", end: "07:00" }, next: { verdict: "waits", reason: "quiet hours" } });
  });

  it("in its credits state, opens on Cursor paused for a usage limit and holding the pick, which Claude Code starts", async () => {
    const s = new DemoServer(fixture(), () => 1000, false, false, "credits");
    const pause = { harness: "cursor", until: 1000 + 2 * 3600, reason: "usage limit" };

    expect(await body(s.fetch("/api/scheduler"))).toMatchObject({ harness: "cursor", pauses: [pause], next: { verdict: "waits", reason: "cursor usage limit" } });
    const claude = await body(s.fetch("/api/scheduler", { method: "PUT", body: JSON.stringify({ harness: "claude" }) }));
    expect(claude).toMatchObject({ harness: "claude", pauses: [pause], next: { verdict: "starting" }, sessionsByHarness: { claude: { limit: 3 }, cursor: { limit: 2 } } });
  });

  it("keeps a crowded board's sessions under the limit by default and at it when the host is over", async () => {
    const crowded = (): DemoFixture => {
      const f = fixture();
      f.flows[0].agents = [...Array.from({ length: 9 }, (_, i) => card(`DEMO-${i + 1}`, "in_progress")), card("DEMO-10", "ready")];
      return f;
    };
    const sessions = (s: { dimensions: { name: string; use: number }[]; inFlight: unknown[] }) => [s.dimensions.find((d) => d.name === "sessions")?.use, s.inFlight.length];

    const calm = await body(new DemoServer(crowded(), () => 1000).fetch("/api/scheduler"));
    const over = await body(new DemoServer(crowded(), () => 1000, false, false, "over").fetch("/api/scheduler"));

    expect(sessions(calm)).toEqual([2, 2]);
    expect(calm.next).toMatchObject({ task: "DEMO-10", verdict: "starting" });
    expect(sessions(over)).toEqual([4, 4]);
  });

  it("names its stand-in sessions without a host, which the demo publisher refuses in a public page", async () => {
    const listed = await new DemoServer(fixture(), () => 1000).fetch("/api/scheduler").then((r) => r.json());

    expect(JSON.stringify(listed)).not.toMatch(/https?:\/\//);
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
    const f = { ...fixture(), roles: {} };
    const native = { ...machine("to_do", [["to_do", "in_progress", "START"], ["in_progress", "done", "FINISH"]], "done"), mainLine: ["to_do", "in_progress", "done"] };
    f.flows = [{ name: "board", machine: native, agents: [card("DEMO-1", "in_progress")] }];
    const s = new DemoServer(f);
    await s.fetch("/api/tasks", { method: "POST", body: JSON.stringify({ title: "Write the docs" }) });

    expect(s.snapshot.flows[0].agents.find((a) => a.id === "DEMO-2")?.state).toBe("to_do");
  });

  it("leaves a task the viewer created in its starting lane while the demo walks, until the viewer moves it", async () => {
    const f = { ...fixture(), roles: {} };
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

  it("refuses a session start with why, and names Claude Code and Cursor, so the Autopilot card draws its harness Segments", async () => {
    const s = new DemoServer(fixture());
    const fetcher = (url: string, init?: RequestInit) => s.fetch(url, init);

    expect(await postStart("DEMO-1", "@agent-standard-high", "claude", fetcher)).toEqual({ ok: false, reason: ROUTES["/api/start"] });
    expect((await fetchHarnesses(fetcher)).harnesses.map((h) => [h.name, h.label, h.sessions])).toEqual([["claude", "Claude Code", true], ["cursor", "Cursor", true]]);
  });
});

const sources = import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts", "!../api/types.gen.ts"], { query: "?raw", import: "default", eager: true });

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
    name: "dagu/deliver", status: "running", runId: "deliver-agent-demo-1", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, pool: "dagu/deliver",
    steps: STEPS.map((name, i) => ({ name, depends: i ? [STEPS[i - 1]] : [], status: "not_started" as const, kind: null, precondition: null, lock: null, last: [] })),
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
    const snap = { ...fixture(), dags: [{ name: "x", status: "succeeded" as const, runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [] }] };

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

describe("the demo's working tasks", () => {
  const finals = (m: Machine, ...ids: string[]): Machine => ({ ...m, states: m.states.map((s) => ({ ...s, final: ids.includes(s.id) })) });
  const BUILD = machine("start", [["start", "red", "RED"], ["red", "green", "GREEN"], ["green", "red", "RED"], ["green", "done", "DONE"]], "done");
  const QA = finals(machine("sec", [["sec", "ui", "PASS"], ["ui", "passed", "PASS"], ["sec", "changed", "CHANGE"], ["ui", "changed", "CHANGE"]]), "passed", "changed");
  const SHIP = machine("start", [["start", "pushed", "PUSH"], ["pushed", "shipped", "SHIP"]], "shipped");
  const WORK: Machine = {
    ...finals(machine("build", [["build", "qa", "BUILT"], ["qa", "ship", "PASSED"], ["ship", "recorded", "SHIPPED"], ["qa", "build", "FIXED"], ["build", "parked", "PARK"], ["qa", "parked", "PARK"], ["ship", "parked", "PARK"]]), "recorded", "parked"),
    submachines: [{ state: "build", machine: "build" }, { state: "qa", machine: "qa" }, { state: "ship", machine: "ship" }].map((s) => ({ ...s, exits: {}, parent: "work", when: "" })),
  };
  const worked = (): Snapshot => ({
    roles: { working: "in_progress" },
    settled: {},
    dags: [],
    flows: [
      { name: "board", machine: { ...BOARD, submachines: [{ state: "in_progress", machine: "work", exits: {}, parent: "board", when: "" }] }, agents: [card("T-1", "in_progress"), card("T-2", "in_progress"), card("T-3", "ready")] },
      { name: "work", machine: WORK, agents: [] },
      { name: "build", machine: BUILD, agents: [] },
      { name: "qa", machine: QA, agents: [] },
      { name: "ship", machine: SHIP, agents: [] },
    ],
  }) as unknown as Snapshot;
  /** A repeatable stream of numbers in [0, 1). */
  const seeded = (seed: number) => () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const flow = (s: Snapshot, name: string) => s.flows.find((f) => f.name === name)!;
  const agent = (s: Snapshot, name: string, task: string) => flow(s, name).agents.find((a) => (a.task ?? a.id) === task);
  /** Plays `steps` ticks with the board held still, calling `each` after every one. */
  const play = (steps: number, each: (s: Snapshot) => void = () => {}, seed = 7) => {
    const random = seeded(seed);
    let s = worked();
    for (let i = 0; i < steps; i++) {
      s = demoStep(s, random);
      flow(s, "board").agents = worked().flows[0].agents;
      each(s);
    }
    return s;
  };

  it("moves every working task often, so a page open on one sees state change within seconds", () => {
    const moves = new Map<string, number>(), last = new Map<string, string>();
    play(200, (s) => {
      for (const task of ["T-1", "T-2"]) {
        const at = ["work", "build", "qa", "ship"].map((n) => agent(s, n, task)?.state).join();
        if (last.get(task) !== at) moves.set(task, (moves.get(task) ?? 0) + 1);
        last.set(task, at);
      }
    });

    expect(moves.get("T-1")).toBeGreaterThan(20);
    expect(moves.get("T-2")).toBeGreaterThan(20);
  });

  it("leaves a task that is not being worked out of the phases", () => {
    const s = play(200);

    for (const name of ["work", "build", "qa", "ship"]) expect(agent(s, name, "T-3")).toBeUndefined();
  });

  it("takes a task through a phase's machine to its end before the task leaves the phase, and through every phase in the machine's order", () => {
    const seen = new Set<string>();
    let before = worked();
    play(600, (s) => {
      for (const task of ["T-1", "T-2"]) {
        const was = agent(before, "work", task)?.state, is = agent(s, "work", task)?.state;
        if (was && is && was !== is) {
          seen.add(`${was}>${is}`);
          if (is !== "build" || was !== "ship") {
            const left = agent(before, was, task)!;
            const ended = flow(before, was).machine.states.filter((x) => x.final).map((x) => x.id);
            expect(ended).toContain(left.state);
          }
        }
      }
      before = structuredClone(s);
    });

    expect(seen).toEqual(new Set(["build>qa", "qa>build", "qa>ship", "ship>build"]));
  });

  it("sends a task back to Build from a QA that found something, and on to the next phase from one that passed", () => {
    let before = worked();
    play(600, (s) => {
      const was = agent(before, "work", "T-1")?.state, is = agent(s, "work", "T-1")?.state;
      if (was === "qa" && is !== "qa") expect(agent(before, "qa", "T-1")!.state).toBe(is === "ship" ? "passed" : "changed");
      before = structuredClone(s);
    });
  });

  it("walks a phase afresh each time a task enters it, the phase's trail only that visit's", () => {
    let before = worked(), entered = 0;
    play(600, (s) => {
      const was = agent(before, "work", "T-1")?.state, is = agent(s, "work", "T-1")?.state;
      if (was && is && was !== is) {
        entered++;
        expect(agent(s, is, "T-1")).toMatchObject({ state: flow(s, is).machine.states.find((x) => x.initial)!.id, trail: [] });
      }
      before = structuredClone(s);
    });

    expect(entered).toBeGreaterThan(5);
  });

  it("starts a task's lap again in Build once it finishes the last phase, its trail starting over rather than growing or dropping", () => {
    let longest = 0;
    const s = play(2000, (x) => {
      longest = Math.max(longest, agent(x, "work", "T-1")?.trail?.length ?? 0);
      expect(agent(x, "work", "T-1")?.state ?? "build").not.toMatch(/recorded|parked/);
    });

    expect(longest).toBeGreaterThan(1);
    expect(longest).toBeLessThan(200);
    expect(agent(s, "work", "T-1")).toBeDefined();
  });

  it("gives the phases' moves to the history a drill-in reads, in the order they were taken", async () => {
    const f = fixture();
    const s = new DemoServer({ ...f, ...worked(), graphs: f.graphs, flows: worked().flows }, () => 40);
    const random = seeded(3);
    for (let i = 0; i < 30; i++) s.step(random);

    const { events } = await (await s.fetch("/api/history?task=T-1&hours=24")).json();

    expect(events.length).toBeGreaterThan(0);
    expect(events.every((e: { machine: string }) => ["work", "build", "qa", "ship"].includes(e.machine))).toBe(true);
  });

  it("leaves a snapshot with no phases walking as it did", () => {
    const random = seeded(5);
    let s: Snapshot = { roles: { working: "in_progress" }, settled: {}, dags: [], flows: [{ name: "delivery", machine: DELIVERY, agents: [] }] } as unknown as Snapshot;
    for (let i = 0; i < 5; i++) s = demoStep(s, random);

    expect(flow(s, "delivery").agents.length).toBeGreaterThan(0);
  });
});
