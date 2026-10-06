import { describe, expect, it } from "vitest";
import { emptyFan, fanRows, LINGER_FAILED_S, LINGER_S, queueRow, stepRuns, track } from "./fan";
import type { ActiveRun, Dag, Pool, RunStatus } from "./types";

const STEPS = ["refuse", "lint", "wait_ci"];
const at = (s: number) => new Date(s * 1000).toISOString();
const run = (runId: string, step: string, o: Partial<ActiveRun> & { start?: number; entered?: number } = {}): ActiveRun => {
  const here = STEPS.indexOf(step);
  return {
    runId,
    status: o.status ?? "running",
    startedAt: at(o.start ?? 1000),
    step,
    stepStartedAt: at(o.entered ?? o.start ?? 1000),
    steps: o.steps ?? Object.fromEntries(STEPS.map((s, i): [string, RunStatus] => [s, !step ? "not_started" : i < here ? "succeeded" : i === here ? "running" : "not_started"])),
  };
};
const queued = (runId: string): ActiveRun => ({ runId, status: "queued", startedAt: "", step: "", stepStartedAt: "", steps: Object.fromEntries(STEPS.map((s): [string, RunStatus] => [s, "not_started"])) });
const dag = (active: ActiveRun[], o: Partial<Dag> = {}): Dag => ({
  name: "deliver",
  status: "running",
  runId: "",
  startedAt: "",
  finishedAt: "",
  steps: STEPS.map((name) => ({ name, depends: [], status: "not_started" as const })),
  active,
  pool: "dagu/deliver",
  ...o,
});
const seen = (d: Dag, now: number) => track(emptyFan(), d, now);

describe("fanRows", () => {
  it("lists the longest-running run first and the queued runs last", () => {
    const d = dag([queued("deliver-task-3"), run("deliver-task-1", "lint", { start: 900 }), run("deliver-task-2", "wait_ci", { start: 500 })]);

    const rows = fanRows(seen(d, 1000), d, 1000);

    expect(rows.map((r) => [r.id, r.state, r.elapsed])).toEqual([
      ["deliver-task-2", "running", 500],
      ["deliver-task-1", "running", 100],
      ["deliver-task-3", "queued", 0],
    ]);
  });

  it("gives each row its current step and the time in it", () => {
    const d = dag([run("deliver-agent-task-2787-abc", "lint", { start: 900, entered: 960 })]);

    const [row] = fanRows(seen(d, 1000), d, 1000);

    expect([row.step, row.inStep]).toEqual(["lint", 40]);
    expect(row.strip.map((s) => s.status)).toEqual(["succeeded", "running", "not_started"]);
  });

  it("names the Board task a run id carries, the longest id that fits and never a prefix of a longer number", () => {
    const d = dag([run("deliver-agent-task-2787-abc", "lint"), run("deliver-agent-task-27-x", "lint"), run("034bIx4Ad8NY2VZQcWEuFE", "lint"), run("deliver-task-99-x", "lint")]);

    const rows = fanRows(seen(d, 1000), d, 1000, ["TASK-27", "TASK-2787", "TASK-9"]);

    expect(Object.fromEntries(rows.map((r) => [r.id, r.task]))).toEqual({
      "deliver-agent-task-2787-abc": "TASK-2787",
      "deliver-agent-task-27-x": "TASK-27",
      "034bIx4Ad8NY2VZQcWEuFE": null,
      "deliver-task-99-x": null,
    });
  });

  it("flashes a row for a moment after its run enters a step", () => {
    const first = dag([run("r1", "refuse", { start: 1000 })]), next = dag([run("r1", "lint", { start: 1000, entered: 1010 })]);
    const fan = track(seen(first, 1000), next, 1010);

    expect(fanRows(fan, next, 1010.5)[0].flash).toBe(true);
    expect(fanRows(fan, next, 1012)[0].flash).toBe(false);
  });
});

describe("a run that ends", () => {
  const before = dag([run("r1", "wait_ci", { start: 900 }), run("r2", "lint", { start: 950 })], { runId: "r2" });

  it("keeps its row in the succeeded colour for the linger, then drops it", () => {
    const after = dag([run("r2", "lint", { start: 950 })], { runId: "r2" });
    const fan = track(seen(before, 1000), after, 1100);

    expect(fanRows(fan, after, 1100).map((r) => [r.id, r.state])).toEqual([["r1", "succeeded"], ["r2", "running"]]);
    expect(fanRows(fan, after, 1100)[0].strip.every((s) => s.status === "succeeded")).toBe(true);
    expect(fanRows(fan, after, 1100 + LINGER_S + 0.1).map((r) => r.id)).toEqual(["r2"]);
  });

  it("holds a failed run twice as long, the failed step in red", () => {
    const failing = dag([run("r1", "lint", { start: 900, steps: { refuse: "succeeded", lint: "failed", wait_ci: "not_started" } })], { runId: "r1" });
    const done = dag([], { runId: "r1", status: "failed" });
    const fan = track(seen(failing, 1000), done, 1100);

    const [row] = fanRows(fan, done, 1100 + LINGER_S + 1);

    expect([row.id, row.state]).toEqual(["r1", "failed"]);
    expect(row.strip.map((s) => s.status)).toEqual(["succeeded", "failed", "not_started"]);
    expect(fanRows(fan, done, 1100 + LINGER_FAILED_S + 0.1)).toEqual([]);
  });

  it("takes the DAG's own status for the latest run and its last-seen steps for any other", () => {
    const gone = dag([], { runId: "r1", status: "failed" });
    const bothEnd = fanRows(track(seen(before, 1000), gone, 1100), gone, 1100).map((r) => [r.id, r.state]);
    const stepFailed = dag([run("r1", "lint", { start: 900, steps: { refuse: "succeeded", lint: "failed", wait_ci: "not_started" } })], { runId: "r2" });
    const otherDone = dag([], { runId: "r2", status: "succeeded" });
    const otherEnds = fanRows(track(seen(stepFailed, 1000), otherDone, 1100), otherDone, 1100).map((r) => [r.id, r.state]);

    expect(bothEnd).toEqual([["r1", "failed"], ["r2", "succeeded"]]);
    expect(otherEnds).toEqual([["r1", "failed"]]);
  });

  it("does not linger a queued run that never started", () => {
    const waiting = dag([queued("r9")]), empty = dag([]);

    expect(fanRows(track(seen(waiting, 1000), empty, 1100), empty, 1100)).toEqual([]);
  });
});

describe("queueRow", () => {
  const pools: Pool[] = [{ name: "dagu/deliver", cap: 32, running: 5, queued: 0 }, { name: "dagu/default", cap: 2, running: 2, queued: 1 }];

  it("reports the pool's running count against its cap, the DAG's share only when the pool is shared", () => {
    const own = dag(Array.from({ length: 5 }, (_, i) => run(`r${i}`, "lint")));
    const shared = dag([run("r1", "lint")], { name: "graph-refresh", pool: "dagu/default" });

    expect(queueRow(own, pools)).toMatchObject({ pool: "deliver", running: 5, cap: 32, mine: 5, full: false });
    expect(queueRow(shared, pools)).toMatchObject({ pool: "default", running: 2, cap: 2, queued: 1, mine: 1, full: true });
  });

  it("draws no row for a DAG whose adapter reports no pool", () => {
    expect(queueRow(dag([], { pool: "" }), pools)).toBeNull();
    expect(queueRow(dag([]), undefined)).toBeNull();
  });
});

describe("step chips", () => {
  const d = dag([run("r1", "lint"), run("r2", "lint"), run("r3", "wait_ci"), queued("r4")]);

  it("counts the running runs in each step", () => {
    expect(STEPS.map((s) => stepRuns(d, s))).toEqual([0, 2, 1]);
  });

});
