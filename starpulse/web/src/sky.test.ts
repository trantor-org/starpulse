import { describe, expect, it } from "vitest";
import { merge, Moves, TRAVEL } from "./sky";
import type { Machine, RawAgent, Snapshot } from "./types";

const machine = (ids: string[], extra: Partial<Machine> = {}): Machine => ({
  states: ids.map((id, i) => ({ id, name: id.replace(/_/g, " "), initial: i === 0, final: false })),
  transitions: [],
  ...extra,
});
const task = (id: string, state: string): RawAgent => ({ id, title: id, state, model: "@agent-deep-high", labels: [], description: `about ${id}` });
const placed = (id: string, trail: [string, string, number][]): RawAgent => ({
  id, title: id, state: trail.at(-1)![0], model: "", task: id, steps: trail.length,
  trail: trail.map(([state, event, at]) => ({ state, event, at })),
});
const snap = (now: number, tasks: RawAgent[], machineTasks: RawAgent[], finishedAt = "2026-09-30T20:00:00Z"): Snapshot => ({
  graphs: ["board", "in-progress", "triaging-cr-reviews", "auditing-docs", "runs"],
  flows: [
    { name: "board", agents: tasks, machine: machine(["ready", "in_progress", "review"], {
      transitions: [{ source: "ready", target: "in_progress", event: "CLAIM" }],
      subflows: [{ state: "in_progress", flow: "in-progress", exits: {}, parent: "board", when: "" }],
      launches: { "board-autopilot": { skill: "starting-tasks", flow: "in-progress" }, "weekly-code-audit": { skill: "auditing-code", flow: null } },
      writers: { CLAIM: [{ actor: "board-autopilot", trigger: "dagu" }] },
    }) },
    { name: "in-progress", agents: machineTasks, machine: machine(["worktree_ready", "pr_opened"], {
      subflows: [{ state: "pr_opened", flow: "triaging-cr-reviews", exits: {}, parent: "in-progress", when: "a PR is open" }],
    }) },
    { name: "triaging-cr-reviews", agents: [], machine: machine(["fetch"]) },
  ],
  dags: [{ name: "board-autopilot", status: "succeeded", runId: "r", startedAt: "", finishedAt, steps: [] }],
  domains: [{ name: "Board", dags: [{ name: "board-autopilot", runSafe: false }, { name: "worktree-reap", runSafe: true }] }],
  cues: [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge to main" }],
  boardUrl: "http://board",
  settled: {},
  error: null,
  now,
});

describe("the sky", () => {
  it("reads the relationships the drawing needs from the Board snapshot", () => {
    const S = merge(snap(1000, [task("PROJ-1", "ready")], []));

    expect(S.groups).toEqual([{ name: "Board", dags: ["board-autopilot", "worktree-reap"] }]);
    expect([...S.runnable]).toEqual(["worktree-reap"]);
    expect(S.launches).toEqual([
      { dag: "board-autopilot", skill: "starting-tasks", flow: "in-progress" },
      { dag: "weekly-code-audit", skill: "auditing-code", flow: null },
    ]);
    expect(S.subs).toEqual({ in_progress: ["in-progress", "auditing-docs"] });
    expect(S.child).toEqual({ "in-progress": { pr_opened: { flow: "triaging-cr-reviews", when: "while a PR is open" } } });
    expect(S.boardUrl).toBe("http://board");
  });
});

describe("a machine's tasks", () => {
  it("carry the Board's title, profile, labels and description beside the place the machine gave them", () => {
    const board = { ...task("PROJ-1", "in_progress"), title: "Draw tasks", model: "@agent-deep-high", labels: ["kind-execute"], dependencies: ["PROJ-0"], prs: ["https://github.com/o/r/pull/7"] };
    const S = merge(snap(1000, [board], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])]));

    const [t] = S.flows["in-progress"].agents;

    expect([t.state, t.steps, t.title, t.model, t.labels, t.dependencies, t.prs, t.description]).toEqual([
      "worktree_ready", 1, "Draw tasks", "@agent-deep-high", ["kind-execute"], ["PROJ-0"], ["https://github.com/o/r/pull/7"], "about PROJ-1",
    ]);
  });

  it("stay as the machine placed them when the Board has no such task", () => {
    const S = merge(snap(1000, [], [placed("PROJ-9", [["worktree_ready", "WORKTREE_READY", 900]])]));

    expect(S.flows["in-progress"].agents[0]).toMatchObject({ id: "PROJ-9", title: "PROJ-9", state: "worktree_ready" });
  });
});

describe("the moves", () => {
  it("keeps a machine task's steps from before the page loaded at the time they happened", () => {
    const m = new Moves();

    m.observe(merge(snap(1000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])])), 1005);

    expect(m.events.map((e) => [e.flow, e.task, e.at, e.from, e.to])).toEqual([["in-progress", "PROJ-1", 905, null, "worktree_ready"]]);
  });

  it("plays each new step when it is seen, one travel after the last, so a burst between snapshots still draws", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])])), 1000);

    m.observe(merge(snap(1004, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900], ["pr_opened", "PR_OPENED", 1001], ["worktree_ready", "FIX", 1002]])])), 1004);

    expect(m.events.slice(1).map((e) => [e.at, e.from, e.to, e.event])).toEqual([
      [1004, "worktree_ready", "pr_opened", "PR_OPENED"],
      [1004 + TRAVEL, "pr_opened", "worktree_ready", "FIX"],
    ]);
  });

  it("turns a task's Board state change between snapshots into the transition's event", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [task("PROJ-1", "ready")], [])), 1000);

    m.observe(merge(snap(1004, [task("PROJ-1", "in_progress"), task("PROJ-2", "ready")], [])), 1004);

    expect(m.events.map((e) => [e.flow, e.task, e.at, e.from, e.to, e.event])).toEqual([
      ["board", "PROJ-1", 1004, "ready", "in_progress", "CLAIM"],
      ["board", "PROJ-2", 1004, null, "ready", "CREATE"],
    ]);
  });

  it("flares a DAG whose run ended since the last poll at the time it is seen", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [], [])), 1000);
    expect(m.flare["board-autopilot"]).toBe(Date.parse("2026-09-30T20:00:00Z") / 1000);

    m.observe(merge(snap(1004, [], [], "2026-09-30T21:00:00Z")), 1004);

    expect(m.flare["board-autopilot"]).toBe(1004);
  });

  it("after a resync, places what changed while the page was away at the time it happened instead of queueing it to play", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [task("PROJ-1", "ready")], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])])), 1000);

    m.resync();
    m.observe(merge(snap(3000, [task("PROJ-1", "in_progress")], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900], ["pr_opened", "PR_OPENED", 2000], ["worktree_ready", "FIX", 2100]])], "2026-09-30T21:00:00Z")), 3000);

    expect(m.events.map((e) => [e.flow, e.at, e.to])).toEqual([
      ["in-progress", 900, "worktree_ready"],
      ["in-progress", 2000, "pr_opened"],
      ["in-progress", 2100, "worktree_ready"],
    ]);
    expect(m.flare["board-autopilot"]).toBe(Date.parse("2026-09-30T21:00:00Z") / 1000);
  });

  it("after a resync, keeps no Board move from before it, so no task is drawn in a state it has since left", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [task("PROJ-1", "ready")], [])), 1000);
    m.observe(merge(snap(1004, [task("PROJ-1", "in_progress")], [])), 1004);

    m.resync();
    m.observe(merge(snap(3000, [task("PROJ-1", "review")], [])), 3000);

    expect(m.events.filter((e) => e.flow === "board")).toEqual([]);
  });

  it("forgets moves older than an hour", () => {
    const m = new Moves();

    m.observe(merge(snap(10000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 5000], ["pr_opened", "PR_OPENED", 9000]])])), 10000);

    expect(m.events.map((e) => e.at)).toEqual([9000]);
  });
});
