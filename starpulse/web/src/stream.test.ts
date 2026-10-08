import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DemoServer } from "./demo";
import { RETRY_MS, applyDelta, openStream } from "./stream";
import type { ActiveRun, Dag, Pool, RawAgent, Snapshot } from "./api";

const agent = (id: string, state: string): RawAgent => ({ id, title: id, state, model: "" });
const board = (agents: RawAgent[], extra: Partial<Snapshot> = {}): Snapshot => ({
  graphs: ["board", "runs"],
  dags: [],
  flows: [{ name: "board", machine: { states: [], transitions: [] } as never, agents }],
  settled: {},
  error: null,
  now: 1,
  ...extra,
});
const ids = (s: Snapshot) => s.flows[0].agents.map((a) => `${a.id}:${a.state}`);

const settled = (state: string) => ({ state, at: null, created: null, title: "t", model: "" });

describe("applyDelta", () => {
  it("replaces the suns with the ones a delta carries", () => {
    const s = board([], { suns: { to_do: 1 } });

    expect(applyDelta(s, { kind: "suns", suns: { done: 1 } }).suns).toEqual({ done: 1 });
    expect(s.suns).toEqual({ to_do: 1 });
  });

  it("replaces a task already on the Board and adds one that is not", () => {
    const s = board([agent("PROJ-1", "to_do")]);

    const moved = applyDelta(s, { kind: "task", id: "PROJ-1", agent: agent("PROJ-1", "in_progress"), settled: null });
    const added = applyDelta(moved, { kind: "task", id: "PROJ-2", agent: agent("PROJ-2", "ready"), settled: null });

    expect(ids(moved)).toEqual(["PROJ-1:in_progress"]);
    expect(ids(added)).toEqual(["PROJ-1:in_progress", "PROJ-2:ready"]);
  });

  it("takes a task off the lanes and records where it went", () => {
    const s = board([agent("PROJ-1", "done"), agent("PROJ-2", "done")]);

    const swept = applyDelta(s, { kind: "task", id: "PROJ-1", agent: null, settled: settled("completed") });

    expect(ids(swept)).toEqual(["PROJ-2:done"]);
    expect(swept.settled).toEqual({ "PROJ-1": settled("completed") });
  });

  it("forgets a task's settled state once it is back in a lane", () => {
    const s = board([], { settled: { "PROJ-1": settled("completed"), "PROJ-2": settled("archived") } });

    const back = applyDelta(s, { kind: "task", id: "PROJ-1", agent: agent("PROJ-1", "to_do"), settled: null });

    expect(back.settled).toEqual({ "PROJ-2": settled("archived") });
  });

  it("takes Dagu's runs and error without touching the tasks", () => {
    const s = board([agent("PROJ-1", "to_do")]);
    const dags = [{ name: "d" } as Dag];

    const next = applyDelta(s, { kind: "dags", dags, error: "ci: down" });

    expect([next.dags, next.error, ids(next)]).toEqual([dags, "ci: down", ["PROJ-1:to_do"]]);
  });

  it("keeps each concurrent run's own step as the deltas of a DAG move one run at a time", () => {
    const run = (runId: string, step: string) =>
      ({ runId, status: "running", startedAt: "", step, stepStartedAt: "", steps: {} }) as ActiveRun;
    const deliver = (...active: ActiveRun[]) => [{ name: "ci/deliver", active } as Dag];
    const s = applyDelta(board([]), { kind: "dags", dags: deliver(run("r1", "refuse"), run("r2", "refuse")), error: null });

    const moved = applyDelta(s, { kind: "dags", dags: deliver(run("r1", "refuse"), run("r2", "lint")), error: null });

    expect(moved.dags[0].active?.map((a) => `${a.runId}:${a.step}`)).toEqual(["r1:refuse", "r2:lint"]);
    expect(s.dags[0].active?.map((a) => `${a.runId}:${a.step}`)).toEqual(["r1:refuse", "r2:refuse"]);
  });

  it("takes the pools a runs delta carries, and keeps the last ones from a delta that carries none", () => {
    const lane: Pool = { name: "ci/deliver", cap: 2, running: 1, queued: 1 };
    const s = board([], { pools: [lane] });

    const emptied = applyDelta(s, { kind: "dags", dags: [], pools: [], error: null });
    const kept = applyDelta(s, { kind: "dags", dags: [], error: null });
    const replaced = applyDelta(s, { kind: "dags", dags: [], pools: [{ ...lane, running: 2 }], error: null });

    expect([emptied.pools, kept.pools, replaced.pools]).toEqual([[], [lane], [{ ...lane, running: 2 }]]);
  });

  it("replaces the pull requests wholesale with the server's latest read", () => {
    const pull = { number: 7, url: "https://github.com/o/r/pull/7", checks: "pass" as const, merged: false, merge_sha: null, merged_at: null, threads: 2, stale: false };
    const s = board([], { pulls: { "PROJ-1": [{ ...pull, number: 6 }], "PROJ-2": [pull] } });

    const next = applyDelta(s, { kind: "pulls", pulls: { "PROJ-1": [pull] } });

    expect(next.pulls).toEqual({ "PROJ-1": [pull] });
  });

  it("keeps each task's latest refused claim beside the ones the snapshot carried", () => {
    const s = board([], { claims: { "TASK-D1": { reason: "old", at: 5 } } });

    const next = applyDelta(applyDelta(s, { kind: "claim", task: "TASK-D2", reason: "TASK-D3 is not Done", at: 9 }), { kind: "claim", task: "TASK-D1", reason: "new", at: 10 });

    expect(next.claims).toEqual({ "TASK-D1": { reason: "new", at: 10 }, "TASK-D2": { reason: "TASK-D3 is not Done", at: 9 } });
    expect(s.claims).toEqual({ "TASK-D1": { reason: "old", at: 5 } });
  });

  it("places a task on the machine a move names, replacing the place it held there, and leaves the Board and the other machines alone", () => {
    const s = board([agent("PROJ-1", "in_progress")]);
    s.flows.push({ name: "in-progress", machine: { states: [], transitions: [] } as never, agents: [agent("PROJ-1", "worktree_ready")] });
    s.flows.push({ name: "auditing-docs", machine: { states: [], transitions: [] } as never, agents: [] });

    const moved = applyDelta(s, { kind: "move", flow: "in-progress", id: "PROJ-1", agent: agent("PROJ-1", "pushed") });
    const added = applyDelta(moved, { kind: "move", flow: "in-progress", id: "PROJ-2", agent: agent("PROJ-2", "worktree_ready") });

    expect(moved.flows.map((f) => f.agents.map((a) => `${a.id}:${a.state}`))).toEqual([["PROJ-1:in_progress"], ["PROJ-1:pushed"], []]);
    expect(added.flows[1].agents.map((a) => `${a.id}:${a.state}`)).toEqual(["PROJ-1:pushed", "PROJ-2:worktree_ready"]);
    expect(s.flows[1].agents.map((a) => a.state)).toEqual(["worktree_ready"]);
  });

  it("leaves the snapshot it was given as it was", () => {
    const s = board([agent("PROJ-1", "to_do")]);

    applyDelta(s, { kind: "task", id: "PROJ-1", agent: null, settled: settled("archived") });

    expect([ids(s), s.settled]).toEqual([["PROJ-1:to_do"], {}]);
  });
});

class FakeSource {
  static made: FakeSource[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((e: { data: string }) => void)[]>();
  constructor(readonly url: string) {
    FakeSource.made.push(this);
  }
  addEventListener(type: string, fn: (e: { data: string }) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  send(type: string, data: unknown) {
    for (const fn of this.listeners.get(type) ?? []) fn({ data: JSON.stringify(data) });
  }
  close() {
    this.readyState = 2;
  }
}
const open = (url: string) => new FakeSource(url) as unknown as EventSource;
const last = () => FakeSource.made[FakeSource.made.length - 1];

describe("openStream", () => {
  const seen: Snapshot[] = [];
  const lives: boolean[] = [];
  const handlers = { snapshot: (s: Snapshot) => void seen.push(s), live: (on: boolean) => void lives.push(on) };

  beforeEach(() => {
    vi.useFakeTimers();
    FakeSource.made = [];
    seen.length = 0;
    lives.length = 0;
  });
  afterEach(() => vi.useRealTimers());

  it("opens one connection to /api/events and hands over its snapshot", () => {
    openStream(handlers, open);

    last().send("snapshot", board([agent("PROJ-1", "to_do")]));

    expect(FakeSource.made.map((f) => f.url)).toEqual(["/api/events"]);
    expect(seen.map(ids)).toEqual([["PROJ-1:to_do"]]);
  });

  it("follows an embedded page's demo server without opening a connection: its moves and its walk reach the page until closed", () => {
    const machine = {
      states: ["new", "to_do", "done"].map((id) => ({ id, name: id, initial: id === "new", final: false })),
      transitions: [{ source: "to_do", target: "done", event: "FINISH" }],
    };
    const server = new DemoServer(board([agent("TASK-D1", "to_do")], { flows: [{ name: "board", machine, agents: [agent("TASK-D1", "to_do")] }] }));

    const stream = openStream(handlers, open, server);
    server.move("TASK-D1", "done");
    vi.advanceTimersByTime(1200);
    const walked = seen.length;
    stream.close();
    vi.advanceTimersByTime(60_000);

    expect(FakeSource.made).toEqual([]);
    expect(lives).toEqual([true]);
    expect(seen.slice(0, 2).map(ids)).toEqual([["TASK-D1:to_do"], ["TASK-D1:done"]]);
    expect([walked, seen.length]).toEqual([3, 3]); // the snapshot, the move, one walk step; nothing once closed
  });

  it("hands over the Board folded with each delta that follows", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("PROJ-1", "to_do")]));

    last().send("task", { id: "PROJ-1", agent: agent("PROJ-1", "in_progress"), settled: null });
    last().send("dags", { dags: [], error: "ci: down" });

    expect(seen.map(ids)).toEqual([["PROJ-1:to_do"], ["PROJ-1:in_progress"], ["PROJ-1:in_progress"]]);
    expect(seen[2].error).toBe("ci: down");
  });

  it("folds the suns a local midnight resized into the snapshot, leaving the Board as it was", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("PROJ-1", "to_do")], { suns: { to_do: 1 } }));

    last().send("suns", { suns: { to_do: 0.5, done: 0.5 } });

    expect(seen.at(-1)!.suns).toEqual({ to_do: 0.5, done: 0.5 });
    expect(ids(seen.at(-1)!)).toEqual(["PROJ-1:to_do"]);
  });

  it("folds the Ledger rows a merge's runs changed into the snapshot", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("PROJ-1", "to_do")]));

    last().send("ledgers", { ledgers: { MERGED: [{ key: "k", at: 1, tasks: [], runs: {}, fails: {}, pinned: false }] } });

    expect(seen.at(-1)!.ledgers?.MERGED.map((r) => r.key)).toEqual(["k"]);
    expect(ids(seen.at(-1)!)).toEqual(["PROJ-1:to_do"]);
  });

  it("folds the 24-hour strip and the pins the head left out with the Ledger rows", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("PROJ-1", "to_do")]));
    const mergeStrip = { since: 0, bucket: 900, buckets: [{ merges: 1, failed: 1, reruns: 0 }] };
    const pin = { key: "p", at: 1, tasks: [], runs: {}, fails: {}, pinned: true };

    last().send("ledgers", { ledgers: { MERGED: [] }, mergeStrip, mergePins: [pin] });

    expect(seen.at(-1)!.mergeStrip).toEqual(mergeStrip);
    expect(seen.at(-1)!.mergePins?.map((r) => r.key)).toEqual(["p"]);
  });

  it("folds a refused claim the writer published into the snapshot", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("TASK-D1", "waiting")]));

    last().send("claim", { task: "TASK-D1", reason: "TASK-D3 is not Done", at: 1001 });

    expect(seen.at(-1)!.claims).toEqual({ "TASK-D1": { reason: "TASK-D3 is not Done", at: 1001 } });
  });

  it("folds a move on a machine into the snapshot without any request but the one stream", () => {
    const fetched = vi.fn();
    vi.stubGlobal("fetch", fetched);
    openStream(handlers, open);
    const snap = board([agent("PROJ-1", "in_progress")]);
    snap.flows.push({ name: "in-progress", machine: { states: [], transitions: [] } as never, agents: [] });
    last().send("snapshot", snap);

    last().send("move", { flow: "in-progress", id: "PROJ-1", agent: agent("PROJ-1", "worktree_ready") });
    vi.advanceTimersByTime(60_000);

    expect(seen.at(-1)!.flows[1].agents.map((a) => `${a.id}:${a.state}`)).toEqual(["PROJ-1:worktree_ready"]);
    expect([fetched.mock.calls.length, FakeSource.made.map((f) => f.url)]).toEqual([0, ["/api/events"]]);
    vi.unstubAllGlobals();
  });

  it("ignores a delta that arrives before any snapshot", () => {
    openStream(handlers, open);

    last().send("task", { id: "PROJ-1", agent: agent("PROJ-1", "to_do"), settled: null });

    expect(seen).toEqual([]);
  });

  it("reports whether the connection is up", () => {
    openStream(handlers, open);

    last().onopen?.();
    last().onerror?.();

    expect(lives).toEqual([true, false]);
  });

  it("lets the browser retry a dropped connection and resyncs from the snapshot the server sends on it", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("PROJ-1", "to_do")]));

    last().onerror?.(); // readyState stays CONNECTING: the browser reconnects the same source
    vi.advanceTimersByTime(RETRY_MS * 2);
    last().send("snapshot", board([agent("PROJ-1", "done")]));

    expect(FakeSource.made).toHaveLength(1);
    expect(seen.map(ids)).toEqual([["PROJ-1:to_do"], ["PROJ-1:done"]]);
  });

  it("keeps the Board it showed while a restarted server is still reading its board, then hands over the Board it read in one piece", () => {
    openStream(handlers, open);
    last().send("snapshot", board([agent("PROJ-1", "to_do"), agent("PROJ-2", "review")]));

    last().onerror?.(); // the server restarted: the browser reconnects the same source
    last().send("snapshot", board([], { reading: true, error: "board: reading q:tasks" }));
    last().send("move", { flow: "board", id: "PROJ-9", agent: agent("PROJ-9", "x") });
    last().send("dags", { dags: [], error: "board: reading q:tasks" });
    last().send("snapshot", board([agent("PROJ-1", "in_progress"), agent("PROJ-2", "review")], { reading: false }));

    expect(seen.map(ids)).toEqual([["PROJ-1:to_do", "PROJ-2:review"], ["PROJ-1:in_progress", "PROJ-2:review"]]);
  });

  it("shows a server that is still reading its board when the page has shown nothing yet", () => {
    openStream(handlers, open);

    last().send("snapshot", board([], { reading: true, error: "board: reading q:tasks" }));

    expect(seen.map((s) => s.error)).toEqual(["board: reading q:tasks"]);
  });

  it("opens a new connection when the browser gives the old one up", () => {
    openStream(handlers, open);
    last().readyState = 2;

    last().onerror?.();
    expect(FakeSource.made).toHaveLength(1);
    vi.advanceTimersByTime(RETRY_MS);

    expect(FakeSource.made).toHaveLength(2);
  });

  it("closes the connection and cancels a pending reopen", () => {
    const stream = openStream(handlers, open);
    const first = last();
    first.readyState = 2;
    first.onerror?.();

    stream.close();
    vi.advanceTimersByTime(RETRY_MS * 2);

    expect(FakeSource.made).toHaveLength(1);
    expect(first.readyState).toBe(2);
  });

  it("closes a live connection", () => {
    const stream = openStream(handlers, open);

    stream.close();

    expect(last().readyState).toBe(2);
  });
});

describe("the page's sources", () => {
  const sources = import.meta.glob<string>(["./*.ts", "./*.tsx", "!./*.test.ts"], { query: "?raw", import: "default", eager: true });

  it("name no snapshot endpoint and keep no timed poll of one: every flow arrives over the stream", () => {
    const polling = Object.entries(sources).filter(([, text]) => /api\/snapshot|fetchSnapshot|\bpoll/i.test(text));

    expect(Object.keys(sources).length).toBeGreaterThan(5);
    expect(polling.map(([file]) => file)).toEqual([]);
  });
});
