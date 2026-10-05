import { describe, expect, it } from "vitest";
import { fmtAt, fmtDur, hostRun, laneRun, draws, layout, machineRun, sessionRings, subjectOf, traceCard, traceTable, type LaneStep, type MachineStep, type Place, type Subject } from "./trace";
import type { Curve } from "./scene";
import type { FlowSnapshot, Machine } from "./types";

const T0 = 1_000_000;
const board: Machine = {
  states: ["new", "ready", "in_progress", "review", "done"].map((id, i) => ({
    id, name: id.replace("_", " ").replace(/^./, (c) => c.toUpperCase()), initial: i === 0, final: id === "done",
  })),
  transitions: [],
};
/** A task with two review loops: created Ready, claimed, sent to review, sent back, reviewed again, then merged. */
const looped: LaneStep[] = [
  { at: T0, from: null, to: "Ready" },
  { at: T0 + 100, from: "Ready", to: "In Progress" },
  { at: T0 + 400, from: "In Progress", to: "Review" },
  { at: T0 + 1000, from: "Review", to: "In Progress" },
  { at: T0 + 1500, from: "In Progress", to: "Review" },
  { at: T0 + 2000, from: "Review", to: "Done" },
];

describe("a task's lane run", () => {
  it("numbers each lane change, sums the stay and visits per state and counts a hop back into a visited state as a loop", () => {
    const run = laneRun(looped, board, T0 + 9999);

    expect(run.hops.map((h) => [h.n, h.from, h.to, h.stay])).toEqual([
      [1, "new", "ready", 100], [2, "ready", "in_progress", 300], [3, "in_progress", "review", 600],
      [4, "review", "in_progress", 500], [5, "in_progress", "review", 500], [6, "review", "done", 0],
    ]);
    expect(run.stay).toEqual({ ready: 100, in_progress: 800, review: 1100, done: 0 });
    expect(run.visits).toEqual({ ready: 1, in_progress: 2, review: 2, done: 1 });
    expect([run.loops, run.total]).toEqual([2, 6]);
  });

  it("ends a finished task where it reached its final state, and a live one now", () => {
    const done = laneRun(looped, board, T0 + 9999), live = laneRun(looped.slice(0, 3), board, T0 + 700);

    expect([done.live, done.start, done.end]).toEqual([false, T0, T0 + 2000]);
    expect([live.live, live.end, live.hops[2].stay]).toEqual([true, T0 + 700, 300]);
  });
});

const skill: Machine = {
  states: ["worktree_ready", "red_proven", "pr_opened", "merged"].map((id, i) => ({ id, name: id, initial: i === 0, final: id === "merged" })),
  transitions: [],
};

describe("a task's run on a lifecycle machine", () => {
  const path: MachineStep[] = [
    { at: T0, event: "WORKTREE_READY", state: "worktree_ready" },
    { at: T0 + 60, event: "RED_PROVEN", state: "red_proven" },
    { at: T0 + 90, event: "RED_PROVEN", state: "red_proven" },
    { at: T0 + 300, event: "PR_OPENED", state: "pr_opened" },
  ];

  it("leaves the initial state with its first event, and counts a step that stays put without drawing a hop", () => {
    const run = machineRun(path, skill, 4, T0 + 1000);

    expect(run.hops.map((h) => [h.n, h.from, h.to, h.stay])).toEqual([[1, "worktree_ready", "red_proven", 240], [2, "red_proven", "pr_opened", 700]]);
    expect([run.total, run.loops, run.live, run.start]).toEqual([4, 0, true, T0]);
  });

  it("takes the step total from the history rather than the rows it holds", () => {
    expect(machineRun(path, skill, 11, T0 + 1000).total).toBe(11);
  });
});

describe("the trace's time display", () => {
  it("shows a stay in its two largest units, from seconds to days", () => {
    expect([45, 125, 3 * 3600 + 9 * 60, 8 * 3600 + 9 * 60, 47 * 3600, 2 * 86400 + 3 * 3600, -5].map(fmtDur)).toEqual(["45s", "2m", "3h 9m", "8h 9m", "47h 0m", "2d 3h", "0s"]);
  });

  it("shows a moment in the operator's Arizona time", () => {
    expect(fmtAt(1790902800)).toBe("Oct 1, 18:00"); // 2026-10-02 01:00 UTC
  });
});

describe("the trace's layout on a level", () => {
  const place = (id: string, x: number, lab = { x, y: 44 }): Place => ({ id, name: id, x, y: 0, r: 10, R: 22, color: "#a78bfa", lab });
  // b's name sits on a>b's middle, where that path's numbers would go
  const places = { a: place("a", 0, { x: 100, y: 0 }), b: place("b", 200), c: place("c", 400) };
  const straight = (from: string, to: string): Curve | null => {
    const a = places[from as "a"], b = places[to as "a"];
    return ["a>b", "b>c"].includes(`${from}>${to}`) ? { p0: a, c: { x: (a.x + b.x) / 2, y: 0 }, p1: b } : null;
  };
  // a to b, b to c, c back to b (a path the machine does not have), then b to c again
  const run = (() => {
    const hop = (n: number, at: number, from: string, to: string, stay: number) => ({ n, at, from, to, stay });
    const hops = [hop(1, 0, "a", "b", 60), hop(2, 60, "b", "c", 3600), hop(3, 3660, "c", "b", 120), hop(4, 3780, "b", "c", 60)];
    return { hops, stay: { b: 180, c: 3780 }, visits: { b: 2, c: 2 }, loops: 2, start: 0, end: 3840, live: true, total: 4 };
  })();

  it("lights each path once, carrying every number it was taken under", () => {
    const { routes } = layout(run, places, straight, true, 1);

    expect(routes.map((r) => [`${r.from.id}>${r.to.id}`, r.nums, r.off])).toEqual([["a>b", [1], false], ["b>c", [2, 4], false], ["c>b", [3], true]]);
  });

  it("bows a hop the machine has no path for off the straight line between its states", () => {
    const off = layout(run, places, straight, true, 1).routes[2];

    expect(off.curve.p0).toBe(places.c);
    expect(off.curve.c.y).not.toBe(0);
  });

  it("sets the summed stay beside each visited state, with the visit count once it was visited again", () => {
    expect(layout(run, places, straight, true, 1).pills.map((p) => [p.place.id, p.text])).toEqual([["b", "3m · 2×"], ["c", "1h 3m · 2×"]]);
  });

  it("slides a path's numbers off its middle when a state's name sits there", () => {
    const [ab] = layout(run, places, straight, true, 1).routes;

    expect(ab.badge).not.toEqual({ x: 100, y: 0 });
    expect(ab.badge.y).toBe(0);
  });

  it("rings the state the run began in only when it never came back to it", () => {
    expect(layout(run, places, straight, true, 1).first).toBe(places.a);
    expect(layout({ ...run, stay: { a: 5, ...run.stay } }, places, straight, true, 1).first).toBeNull();
  });
});

describe("a Board task's sessions", () => {
  const agent = (id: string, task: string, state: string) => ({ id, task, state, title: "", model: "" });
  const flow = (name: string, agents: ReturnType<typeof agent>[]): FlowSnapshot => ({ name, machine: { states: [], transitions: [] }, agents });
  const flows = Object.fromEntries([
    flow("board", [agent("PROJ-1", "", "in_progress")]),
    flow("in-progress", [agent("s1", "PROJ-1", "red_proven"), agent("s2", "PROJ-1", "worktree_ready"), agent("s3", "PROJ-9", "pr_opened")]),
    flow("triaging-cr-reviews", [agent("s4", "PROJ-1", "fetch")]),
  ].map((f) => [f.name, f]));
  const moons = ["in-progress", "triaging-cr-reviews", "idle"].map((name) => ({ name }));
  const subs = [{ machine: "in-progress", state: "pr_opened" }, { machine: "in-progress", state: "red_proven" }];

  it("rings each moon it has a session in with the count, and the sub-state a session holds", () => {
    const rings = sessionRings(flows, "PROJ-1", moons, subs);

    expect(rings.moons.map(([m, n]) => [m.name, n])).toEqual([["in-progress", 2], ["triaging-cr-reviews", 1]]);
    expect(rings.subs).toEqual([subs[1]]);
  });

  it("rings nothing for a task with no session", () => {
    expect(sessionRings(flows, "PROJ-404", moons, subs)).toEqual({ moons: [], subs: [] });
  });
});

describe("the hover card and the pinned panel's hop table", () => {
  const head = { kind: "task · In Progress · click to pin its path", id: "PROJ-7", title: "Draw the trace", goal: "Done" };
  const live = laneRun(looped.slice(0, 4), board, T0 + 3 * 3600), finished = laneRun(looped, board, T0 + 9999);

  it("shows a live run's steps, loops and time so far, when it began in Arizona time, and the forecast slot", () => {
    const card = traceCard(head, live);

    expect(card).toContain("PROJ-7");
    expect(card).toContain("<b>4</b> steps");
    expect(card).toContain("<b>1</b> loop</span>");
    expect(card).toContain("<b>3h 0m</b> so far");
    expect(card).toContain("since Jan 12, 06:46 MST");
    expect(card).toContain("Proposal D, not built");
  });

  it("shows a finished run from start to end with no forecast", () => {
    const card = traceCard(head, finished);

    expect(card).toContain("<b>33m</b> start to end");
    expect(card).not.toContain("forecast");
  });

  it("says so while the history loads or when it cannot be had, and escapes what it was given", () => {
    expect(traceCard(head, "loading")).toContain("tracing its path");
    expect(traceCard(head, "unavailable")).toContain("history unavailable");
    expect(traceCard({ ...head, title: "<b>x</b>" }, "loading")).toContain("&lt;b&gt;x&lt;/b&gt;");
  });

  it("lists every hop with its number, when, states and stay", () => {
    const table = traceTable(finished, (id) => board.states.find((s) => s.id === id)!.name);

    expect(table).toContain("path · 6 steps · 2 loops · 33m");
    expect(table).toContain("<tr><td>4</td><td>Jan 12, 07:03</td><td>Review → In progress</td><td>8m</td></tr>");
    expect(table.match(/<tr>/g)).toHaveLength(6);
  });
});

describe("what a hover draws", () => {
  const task = { kind: "task", o: { id: "PROJ-7" } }, other = { kind: "task", o: { id: "PROJ-8" } };
  const ses = { kind: "mtask", o: { id: "PROJ-7", flow: "in-progress" } };
  const dag = { kind: "dag", o: { name: "board-autopilot" } };
  const pin: Subject = { kind: "task", id: "PROJ-7" };

  it("traces a hovered task or machine task but only highlights: nothing is veiled until a click pins it", () => {
    expect(draws(task, null)).toEqual({ trace: { subject: { kind: "task", id: "PROJ-7" }, veil: false }, dag: null });
    expect(draws(ses, null).trace).toEqual({ subject: { kind: "mtask", id: "PROJ-7", flow: "in-progress" }, veil: false });
  });

  it("veils from the click itself, even while the pointer still rests on the dot", () => {
    expect(draws(task, subjectOf(task))).toEqual({ trace: { subject: pin, veil: true }, dag: null });
    expect(draws(null, pin).trace).toEqual({ subject: pin, veil: true });
  });

  it("traces another hovered task without a veil while one stays pinned", () => {
    expect(draws(other, pin).trace).toEqual({ subject: { kind: "task", id: "PROJ-8" }, veil: false });
  });

  it("draws no DAG tether for a hovered task and no trace for a hovered DAG", () => {
    expect(draws(task, null).dag).toBeNull();
    expect(draws(ses, null).dag).toBeNull();
    expect(draws(dag, null)).toEqual({ trace: null, dag: dag.o });
  });

  it("draws nothing for any other hover", () => {
    expect(draws({ kind: "state", o: {} }, null)).toEqual({ trace: null, dag: null });
    expect(draws(null, null)).toEqual({ trace: null, dag: null });
  });
});

describe("a task's run across a state level's bodies", () => {
  it("starts from the Board lane the task entered from, so a task with no moves here still holds the body it orbits", () => {
    const run = hostRun([], 1000, undefined, { at: 400, from: "Ready", to: "in-progress" });
    expect(run.hops).toEqual([{ n: 1, at: 400, from: "Ready", to: "in-progress", stay: 600 }]);
    expect(run.stay).toEqual({ "in-progress": 600 });
  });

  it("numbers each move between bodies and counts a return to one as a loop, still live at its end", () => {
    const run = hostRun([{ at: T0, host: "in-progress" }, { at: T0 + 100, host: "triaging" }, { at: T0 + 100, host: "triaging" }, { at: T0 + 300, host: "in-progress" }], T0 + 500);

    expect(run.hops.map((h) => [h.n, h.from, h.to])).toEqual([[1, "in-progress", "triaging"], [2, "triaging", "in-progress"]]);
    expect([run.stay, run.loops, run.live, run.total]).toEqual([{ triaging: 200, "in-progress": 200 }, 1, true, 2]);
  });
  it("weaves the primary's recorded path in with the event trail, in time order", () => {
    const path = [{ at: T0, event: "WORKTREE", state: "worktree_ready" }, { at: T0 + 200, event: "OPEN_PR", state: "pr_opened" }];
    const run = hostRun([{ at: T0 + 100, host: "triaging" }, { at: T0 + 150, host: "in-progress#worktree_ready" }], T0 + 500, { flow: "in-progress", path });

    expect(run.hops.map((h) => [h.from, h.to])).toEqual([["in-progress#worktree_ready", "triaging"], ["triaging", "in-progress#worktree_ready"], ["in-progress#worktree_ready", "in-progress#pr_opened"]]);
  });
});
