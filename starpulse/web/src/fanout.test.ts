import { describe, expect, it } from "vitest";
import { poolRows, RunEvents } from "./fanout";
import type { ActiveRun, Dag, Pool, RunStatus } from "./types";

const pool = (name: string, cap: number, running: number, queued = 0): Pool => ({ name, cap, running, queued });

describe("the navigator's pool rows", () => {
  it("writes each pool's running count against its cap", () => {
    const [row] = poolRows([pool("dagu/deliver", 32, 5)]);

    expect(row).toMatchObject({ label: "deliver", count: "5/32", queued: "", full: false, busy: true });
    expect(row.pct).toBeCloseTo(15.625);
  });

  it("adds the queued runs as +q and nothing when none wait", () => {
    const rows = poolRows([pool("dagu/deliver", 32, 32, 6), pool("dagu/default", 2, 1)]);

    expect(rows.map((r) => r.queued)).toEqual(["+6", ""]);
  });

  it("is full, and so red, once the pool runs its cap, and only then", () => {
    const rows = poolRows([pool("dagu/deliver", 32, 32), pool("dagu/models", 1, 1), pool("dagu/gpu-1", 1, 0), pool("dagu/default", 2, 1)]);

    expect(rows.map((r) => r.full)).toEqual([true, true, false, false]);
    expect(rows.map((r) => r.pct)).toEqual([100, 100, 0, 50]);
  });

  it("is idle, with no colour, while nothing runs", () => {
    expect(poolRows([pool("dagu/models", 1, 0)])[0]).toMatchObject({ busy: false, full: false, count: "0/1" });
  });

  it("draws a pool with no cap as empty rather than dividing by zero", () => {
    expect(poolRows([pool("dagu/paused", 0, 0)])[0]).toMatchObject({ pct: 0, full: false });
  });

  it("names a pool by its bare name unless another instance runs one by it", () => {
    expect(poolRows([pool("dagu/deliver", 32, 0), pool("other/default", 2, 0)]).map((r) => r.label)).toEqual(["deliver", "default"]);
    expect(poolRows([pool("dagu/default", 2, 0), pool("other/default", 2, 0)]).map((r) => r.label)).toEqual(["dagu/default", "other/default"]);
  });

  it("lists no row when the adapter reports no pools", () => {
    expect(poolRows(undefined)).toEqual([]);
    expect(poolRows([])).toEqual([]);
  });
});

const run = (runId: string, status: RunStatus, step: string, steps: Record<string, RunStatus> = {}): ActiveRun => ({
  runId, status, startedAt: "2026-10-05T16:00:00Z", step, stepStartedAt: "2026-10-05T16:00:05Z", steps,
});
const dag = (active: ActiveRun[], over: Partial<Dag> = {}): Dag => ({
  name: "dagu/deliver", status: "running", runId: "", startedAt: "", finishedAt: "", steps: [], active, ...over,
});
const A = "deliver-agent-task-2787-1", B = "deliver-agent-task-2801-2";

describe("the Recent feed's run lines", () => {
  it("writes nothing for the runs already in flight when the page first reads them", () => {
    const events = new RunEvents();

    events.observe([dag([run(A, "running", "lint")])], 100);

    expect(events.lines).toEqual([]);
  });

  it("writes a started line, naming the task the run id embeds, when a running run appears", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run(A, "running", "refuse")])], 101);

    expect(events.lines).toMatchObject([{ who: "deliver", where: "started · TASK-2787", at: 101, tone: undefined, fresh: true }]);
  });

  it("writes a queued line for a run that appears queued, then a started line when it starts", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run(A, "queued", "")])], 101);
    events.observe([dag([run(A, "running", "refuse")])], 105);

    expect(events.lines.map((l) => l.where)).toEqual(["started · TASK-2787", "queued · TASK-2787"]);
  });

  it("writes the step a run enters, and only when its step changes", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "refuse")])], 100);

    events.observe([dag([run(A, "running", "refuse")])], 101);
    events.observe([dag([run(A, "running", "lint")])], 102);

    expect(events.lines.map((l) => l.where)).toEqual(["lint · TASK-2787"]);
  });

  it("follows each run on its own, so two runs of one DAG at different steps each write their step", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "lint"), run(B, "running", "lint")])], 100);

    events.observe([dag([run(A, "running", "wait_ci"), run(B, "running", "lint")])], 101);
    events.observe([dag([run(A, "running", "wait_ci"), run(B, "running", "commit")])], 102);

    expect(events.lines.map((l) => l.where)).toEqual(["commit · TASK-2801", "wait_ci · TASK-2787"]);
  });

  it("writes a green succeeded line when a run leaves active with every step it reached done", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "ready", { lint: "succeeded", ready: "running" })])], 100);

    events.observe([dag([])], 101);

    expect(events.lines).toMatchObject([{ who: "deliver", where: "succeeded · TASK-2787", tone: "ok", runId: A }]);
  });

  it("writes a red failed line, naming the step, when a run leaves active having failed in it", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "lint", { lint: "running" })])], 100);
    events.observe([dag([run(A, "running", "lint", { lint: "failed" })])], 101);

    events.observe([dag([])], 102);

    expect(events.lines[0]).toMatchObject({ where: "failed at lint · TASK-2787", tone: "failed", runId: A });
  });

  it("takes the outcome of the DAG's own latest run from the DAG when the run is it", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "ready", { ready: "running" })], { runId: A })], 100);

    events.observe([dag([], { runId: A, status: "failed" })], 101);

    expect(events.lines[0]).toMatchObject({ where: "failed · TASK-2787", tone: "failed" });
  });

  it("names a demo run after the demo task its id embeds", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run("deliver-agent-demo-4", "running", "refuse")])], 101);

    expect(events.lines[0].where).toBe("started · DEMO-4");
  });

  it("falls back to the run id when it embeds no task", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run("nightly-20261005", "running", "a")])], 101);

    expect(events.lines[0].where).toBe("started · nightly-20261005");
  });

  it("keeps the newest dozen lines, newest first", () => {
    const events = new RunEvents();
    events.observe([dag([])], 0);

    for (let i = 1; i <= 15; i++) events.observe([dag([run(`deliver-task-${i}`, "running", "a")])], i);

    expect(events.lines).toHaveLength(12);
    expect(events.lines[0].at).toBe(15);
  });

  it("starts afresh after a resync, so a reconnect's runs are not announced as new", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "lint")])], 100);

    events.resync();
    events.observe([dag([run(A, "running", "lint"), run(B, "running", "refuse")])], 101);

    expect(events.lines).toEqual([]);
  });
});
