import { describe, expect, it } from "vitest";
import { countText, merge, Moves, RING, stateCount, TRAVEL } from "./sky";
import type { ActiveRun, Dag, Machine, RawAgent, Snapshot } from "./api";

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
  it("puts each task created since midnight on the starting state and each settled since midnight on where it settled", () => {
    const midnight = 1000, base = snap(5000, [], []), board = base.flows[0];
    board.machine.states.push({ id: "completed", name: "completed", initial: false, final: true }, { id: "archived", name: "archived", initial: false, final: true });
    board.agents = [{ ...task("PROJ-1", "review"), created: 1500 }, { ...task("PROJ-2", "ready"), created: 900 }];
    base.settled = {
      "PROJ-3": { state: "completed", at: 1200, created: 1100, title: "shipped", model: "@agent-deep-high" },
      "PROJ-4": { state: "archived", at: 1300, created: 10, title: "dropped", model: "" },
      "PROJ-5": { state: "completed", at: 999, created: 10, title: "yesterday", model: "" },
    };

    const today = merge(base, midnight).today;

    const ids = (sid: string) => (today[sid] ?? []).map((a) => [a.id, a.title, a.state, a.today]);
    expect(ids("ready")).toEqual([["PROJ-1", "PROJ-1", "ready", true], ["PROJ-3", "shipped", "ready", true]]);
    expect(ids("completed")).toEqual([["PROJ-3", "shipped", "completed", true]]);
    expect(ids("archived")).toEqual([["PROJ-4", "dropped", "archived", true]]);
    expect(Object.keys(today).sort()).toEqual(["archived", "completed", "ready"]);
  });
  it("counts a task still in a final lane by when it entered it, as a board whose final state keeps its tasks does", () => {
    const base = snap(5000, [{ ...task("PROJ-1", "completed"), entered: 1500 }, { ...task("PROJ-2", "completed"), entered: 900 }], []);
    base.flows[0].machine.states.push({ id: "completed", name: "completed", initial: false, final: true });

    expect((merge(base, 1000).today.completed ?? []).map((a) => a.id)).toEqual(["PROJ-1"]);
  });
  it("counts a starting or terminal state by the day's arrivals and any other by the tasks in it", () => {
    const base = snap(5000, [{ ...task("PROJ-1", "review"), created: 1500 }, task("PROJ-2", "review")], []);
    base.flows[0].machine.states.push({ id: "completed", name: "completed", initial: false, final: true });
    base.settled = { "PROJ-3": { state: "completed", at: 1200, created: 10, title: "shipped", model: "" } };
    const S = merge(base, 1000);

    expect(["ready", "review", "completed"].map((sid) => stateCount(S, sid))).toEqual([1, 2, 1]);
  });
  it("counts a starting state by the day's arrivals alone, leaving out a task in its lane that did not arrive today", () => {
    const base = snap(5000, [{ ...task("PROJ-1", "ready"), created: 1500 }, { ...task("PROJ-2", "ready"), created: 10 }], []);

    expect(stateCount(merge(base, 1000), "ready")).toBe(1);
  });
  it("reads a starting or terminal state's count as the day's, saying how many it holds when some did not arrive today", () => {
    expect([countText(5), countText(4, 4), countText(6, 4), countText(0, 0)]).toEqual(["5", "4 today", "6 · 4 today", "0 today"]);
  });


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

  it("carries each task's latest refused claim, and none when the snapshot names none", () => {
    const claims = { "TASK-D1": { reason: "TASK-D3 is not Done", at: 900 } };

    expect(merge({ ...snap(1000, [task("TASK-D1", "ready")], []), claims }).claims).toEqual(claims);
    expect(merge(snap(1000, [task("TASK-D1", "ready")], [])).claims).toEqual({});
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

    m.resync(1000);
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

    m.resync(1004);
    m.observe(merge(snap(3000, [task("PROJ-1", "review")], [])), 3000);

    expect(m.events.filter((e) => e.flow === "board")).toEqual([]);
  });

  it("queues a task's moves at most one travel ahead, so a burst nobody watched cannot bank a replay", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])])), 1000);

    for (let i = 1; i <= 20; i++) m.observe(merge(snap(1000, [], [placed("PROJ-1", Array.from({ length: i + 1 }, (_, k) => ["worktree_ready", `STEP${k}`, 900 + k * 101] as [string, string, number]))])), 1000 + i);

    expect(Math.max(...m.events.map((e) => e.at))).toBeLessThanOrEqual(1020 + TRAVEL);
  });

  it("after a resync, plays nothing it had queued ahead and starts each task's queue afresh", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [task("PROJ-1", "ready")], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])])), 1000);
    m.observe(merge(snap(1000, [task("PROJ-1", "ready")], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900], ["pr_opened", "PR_OPENED", 1001], ["worktree_ready", "FIX", 1002]])])), 1002);

    m.resync(1002);
    m.observe(merge(snap(1003, [task("PROJ-1", "ready")], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900], ["pr_opened", "PR_OPENED", 1001], ["worktree_ready", "FIX", 1002], ["pr_opened", "PR_OPENED", 1003]])])), 1003);

    expect(m.events.filter((e) => e.at > 1003)).toEqual([]);
    expect(m.events.at(-1)).toMatchObject({ event: "PR_OPENED", to: "pr_opened" });
  });

  it("after a resync, places a delta's steps at the time they happened, though a delta leaves the snapshot's clock behind", () => {
    const m = new Moves();
    m.observe(merge(snap(1000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900]])])), 1000);

    m.resync(1060);
    m.observe(merge(snap(1000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 900], ["pr_opened", "PR_OPENED", 1050]])])), 1060);

    expect(m.events.at(-1)).toMatchObject({ event: "PR_OPENED", at: 1050 });
  });

  it("forgets moves older than an hour", () => {
    const m = new Moves();

    m.observe(merge(snap(10000, [], [placed("PROJ-1", [["worktree_ready", "WORKTREE_READY", 5000], ["pr_opened", "PR_OPENED", 9000]])])), 10000);

    expect(m.events.map((e) => e.at)).toEqual([9000]);
  });
});

describe("a page opened while the server is still reading its board", () => {
  it("places the Board the server finished reading at once instead of moving every task onto it", () => {
    const m = new Moves();
    m.observe(merge({ ...snap(1000, [], [placed("PROJ-1", [["worktree_ready", "START", 900]])]), reading: true }), 1000);

    m.observe(merge(snap(1010, [task("PROJ-1", "in_progress"), task("PROJ-2", "review")], [placed("PROJ-1", [["worktree_ready", "START", 900], ["pr_opened", "PR_OPENED", 1005]])])), 1010);

    expect(m.events.filter((e) => e.flow === "board")).toEqual([]);
    expect(m.events.filter((e) => e.event === "PR_OPENED").map((e) => e.at)).toEqual([1005]);
  });
});

describe("the step rings a run raises", () => {
  const entered = (runId: string, step: string): ActiveRun => ({ runId, status: "running", startedAt: "", step, stepStartedAt: "", steps: { lint: "not_started", push: "not_started" } });
  const withRuns = (now: number, active: ActiveRun[]): Snapshot => {
    const s = snap(now, [], []);
    const dag: Dag = { name: "deliver", status: "running", runId: "a", startedAt: "", finishedAt: "", steps: [{ name: "lint", depends: [], status: "not_started", kind: null }, { name: "push", depends: ["lint"], status: "not_started", kind: null }], active, pool: "deliver" };
    return { ...s, dags: [dag], pools: [{ name: "deliver", cap: 32, running: active.length, queued: 0 }] };
  };

  it("carries the snapshot's pools", () => {
    expect(merge(withRuns(1000, [entered("a", "lint")])).pools).toEqual([{ name: "deliver", cap: 32, running: 1, queued: 0 }]);
    expect(merge(snap(1000, [], [])).pools).toEqual([]);
  });

  it("rings the step a run entered between two snapshots, at the time it is seen", () => {
    const m = new Moves();
    m.observe(merge(withRuns(1000, [entered("a", "lint")])), 1000);
    expect(m.rings).toEqual([]);

    m.observe(merge(withRuns(1004, [entered("a", "push")])), 1004);

    expect(m.rings).toEqual([{ dag: "deliver", step: "push", status: "running", at: 1004 }]);
  });

  it("drops a ring once it has faded, and rings nothing after a resync", () => {
    const m = new Moves();
    m.observe(merge(withRuns(1000, [entered("a", "lint")])), 1000);
    m.observe(merge(withRuns(1004, [entered("a", "push")])), 1004);
    m.observe(merge(withRuns(1004 + RING + 1, [entered("a", "push")])), 1004 + RING + 1);
    expect(m.rings).toEqual([]);

    m.resync(2000);
    m.observe(merge(withRuns(2001, [entered("a", "lint")])), 2001);
    expect(m.rings).toEqual([]);
  });
});

describe("the suns a snapshot carries", () => {
  it("are each Board state's share of the week's moves, and none when the server sent none", () => {
    expect(merge({ ...snap(1000, [], []), suns: { ready: 0.25, review: 0.75 } }, 1000).suns).toEqual({ ready: 0.25, review: 0.75 });
    expect(merge(snap(1000, [], []), 1000).suns).toEqual({});
  });
});
