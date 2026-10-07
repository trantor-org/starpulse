import { describe, expect, it } from "vitest";
import { NO_PREFS, applySuggestion, applyTaskRecord, assigneeOptions, chainOf, columnsOf, filtersActive, hideMilestone, hideTask, holdCounts, holders, kanbanTasks, labelSuggestions, layout, milestoneOptions, milestoneOutline, show, showAll, stackOf, toggleFold, whyHidden, type KanbanTask } from "./kanban";
import { merge } from "./sky";
import type { TaskRecord } from "./taskView";
import type { Pull, RawAgent, Snapshot } from "./types";

const NAMES = { ready: "Ready", waiting: "Waiting", in_progress: "In progress", review: "Review", needs_attention: "Needs attention", done: "Done" };
const task = (id: string, lane: string, milestone = "", at = 0, entered = 0): KanbanTask => ({
  id, title: id, lane, milestone, labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: at ? { machine: "m", state: "s", at } : null, released: false, moves: {}, entered,
});
const view = (tasks: KanbanTask[], prefs = NO_PREFS) => layout(tasks, NAMES, prefs);
const column = (v: ReturnType<typeof view>, id: string) => v.columns.find((c) => c.id === id)!;
const headers = (v: ReturnType<typeof view>, id: string) => column(v, id).buckets.map((b) => b.milestone);

describe("the columns", () => {
  it("are the six Board states in order, named by the machine, and draw no other lane", () => {
    const v = view([task("PROJ-1", "new"), task("PROJ-2", "ready")]);

    expect(v.columns.map((c) => c.name)).toEqual(["Ready", "Waiting", "In progress", "Review", "Needs attention", "Done"]);
    expect(v.columns.map((c) => c.count)).toEqual([1, 0, 0, 0, 0, 0]);
  });

  it("are the board's own lanes in order when it has no ready lane, so a native board's first-lane task is drawn", () => {
    const native = { to_do: "To Do", in_progress: "In Progress", done: "Done" };
    const v = layout([task("TASK-1", "to_do"), task("TASK-2", "done")], native, NO_PREFS);

    expect(columnsOf(native)).toEqual(["to_do", "in_progress", "done"]);
    expect(v.columns.map((c) => [c.id, c.name, c.count])).toEqual([["to_do", "To Do", 1], ["in_progress", "In Progress", 0], ["done", "Done", 1]]);
    expect(v.shown).toBe(2);
    expect(assigneeOptions([task("TASK-1", "to_do")], columnsOf(native))).toEqual([{ value: "", count: 1 }]);
  });

  it("order a column's cards by when each entered the column, newest first, then by id, newest first", () => {
    const v = view([task("PROJ-1", "ready", "", 0, 10), task("PROJ-2", "ready", "", 0, 30), task("PROJ-9", "ready", "", 0, 20), task("PROJ-10", "ready", "", 0, 20)]);

    expect(column(v, "ready").buckets[0].tasks.map((t) => t.id)).toEqual(["PROJ-2", "PROJ-10", "PROJ-9", "PROJ-1"]);
  });

  it("hold a card's place when only its session activity advances", () => {
    const ids = (at: number) => column(view([task("PROJ-1", "in_progress", "", at, 10), task("PROJ-2", "in_progress", "", 5, 20)]), "in_progress").buckets[0].tasks.map((t) => t.id);

    expect(ids(1)).toEqual(["PROJ-2", "PROJ-1"]);
    expect(ids(99)).toEqual(ids(1));
  });
});

describe("milestone buckets", () => {
  const tasks = [
    task("PROJ-1", "ready", "m-9"), task("PROJ-2", "ready", ""), task("PROJ-3", "ready", "m-12"),
    task("PROJ-4", "review", "m-10"), task("PROJ-5", "review", "m-12"), task("PROJ-6", "review", ""),
  ];

  it("run newest milestone first by number, not text, with No milestone last, in every column", () => {
    const v = view(tasks);

    expect(headers(v, "ready")).toEqual(["m-12", "m-9", ""]);
    expect(headers(v, "review")).toEqual(["m-12", "m-10", ""]);
    expect(column(v, "ready").buckets.map((b) => b.tasks.length)).toEqual([1, 1, 1]);
  });

  it("fold in every column when one header folds, and open again on the second click", () => {
    const folded = view(tasks, toggleFold(NO_PREFS, "m-12"));

    expect(["ready", "review"].map((id) => column(folded, id).buckets.find((b) => b.milestone === "m-12")!.folded)).toEqual([true, true]);
    expect(["ready", "review"].map((id) => column(folded, id).buckets.find((b) => b.milestone === "")!.folded)).toEqual([false, false]);
    expect(column(folded, "ready").count).toBe(3);

    const open = view(tasks, toggleFold(toggleFold(NO_PREFS, "m-12"), "m-12"));
    expect(open.columns.flatMap((c) => c.buckets).some((b) => b.folded)).toBe(false);
  });
});

describe("hiding", () => {
  const tasks = [
    task("PROJ-1", "ready", "m-12"), task("PROJ-2", "ready", "m-12"), task("PROJ-3", "ready", "m-9"),
    task("PROJ-4", "in_progress", "m-12"), task("PROJ-5", "done", "m-9"),
  ];

  it("takes a hidden milestone out of every column and the counts", () => {
    const v = view(tasks, hideMilestone(NO_PREFS, "m-12"));

    expect(headers(v, "ready")).toEqual(["m-9"]);
    expect(column(v, "in_progress").buckets).toEqual([]);
    expect(v.columns.map((c) => c.count)).toEqual([1, 0, 0, 0, 0, 1]);
    expect([v.open, v.done, v.shown, v.total]).toEqual([1, 1, 2, 5]);
  });

  it("takes a hidden task out of its column and the counts, and leaves its milestone's other cards", () => {
    const v = view(tasks, hideTask(NO_PREFS, "PROJ-1"));

    expect(column(v, "ready").buckets.find((b) => b.milestone === "m-12")!.tasks.map((t) => t.id)).toEqual(["PROJ-2"]);
    expect(column(v, "ready").count).toBe(2);
    expect(v.shown).toBe(4);
  });

  it("shows one item back, or everything at once", () => {
    const hidden = hideTask(hideMilestone(NO_PREFS, "m-12"), "PROJ-3");

    expect(view(tasks, hidden).shown).toBe(1);
    expect(view(tasks, show(hidden, "milestone", "m-12")).shown).toBe(4);
    expect(view(tasks, show(hidden, "task", "PROJ-3")).shown).toBe(2);
    expect(view(tasks, showAll(hidden)).shown).toBe(5);
    expect(showAll(hidden)).toEqual(NO_PREFS);
  });

  it("lists what is hidden, so the Hidden chip can name it and shows only while something is", () => {
    expect(view(tasks).hidden).toBe(0);
    expect(view(tasks, hideTask(hideMilestone(NO_PREFS, "m-12"), "PROJ-3")).hidden).toBe(2);
  });

  it("never mutates the prefs it was given", () => {
    const before = hideMilestone(NO_PREFS, "m-12");
    hideTask(before, "PROJ-1");
    toggleFold(before, "m-9");

    expect([...before.hiddenTasks, ...before.folded]).toEqual([]);
    expect([...NO_PREFS.hiddenMilestones]).toEqual([]);
  });
});

describe("the cards drawn from a snapshot", () => {
  const pull = (number: number, checks: Pull["checks"], threads = 0): Pull => ({ number, url: `https://github.com/o/r/pull/${number}`, checks, merged: false, merge_sha: null, merged_at: null, threads, stale: false });
  const agent = (id: string, state: string, extra: Partial<RawAgent> = {}): RawAgent => ({ id, title: `title ${id}`, state, model: "", ...extra });
  const machine = { states: [], transitions: [] } as never;
  const snapshot = (): Snapshot => ({
    graphs: ["board", "dagu", "in-progress"],
    dags: [],
    flows: [
      { name: "board", machine, agents: [
        agent("PROJ-1", "in_progress", { model: "@alice", milestone: "m-12", labels: ["size-8"], dependencies: ["PROJ-2", "PROJ-3", "PROJ-4"], prs: ["https://github.com/o/r/pull/7"] }),
        agent("PROJ-2", "review"), agent("PROJ-3", "done"),
      ] },
      { name: "in-progress", machine, agents: [agent("PROJ-1", "pr_opened", { task: "PROJ-1", active: 500 })] },
    ],
    pulls: { "PROJ-1": [pull(7, "pass", 2)] },
    settled: { "PROJ-4": { state: "completed", at: null, created: null, title: "t", model: "" } },
    error: null,
    now: 600,
  });

  it("carry the milestone, profile, labels, pull requests and the machine that last placed the task", () => {
    const [t] = kanbanTasks(merge(snapshot())).filter((x) => x.id === "PROJ-1");

    expect(t).toMatchObject({
      lane: "in_progress", milestone: "m-12", assignee: "@alice", labels: ["size-8"], prs: [pull(7, "pass", 2)],
      live: { machine: "in-progress", state: "pr_opened", at: 500 },
    });
  });

  it("carry the verdict on each column the task may move to, and none for a task the snapshot gives none", () => {
    const moves = { review: { allowed: false, reason: "no render approval", skill: "designing-ui" }, ready: { allowed: true, reason: "", skill: "" } };
    const snap = snapshot();
    snap.flows[0].agents[0].moves = moves;
    const tasks = kanbanTasks(merge(snap));

    expect(tasks.find((t) => t.id === "PROJ-1")!.moves).toEqual(moves);
    expect(tasks.find((t) => t.id === "PROJ-2")!.moves).toEqual({});
  });

  it("count a dependency open only while it is on the Board and not Done", () => {
    const tasks = kanbanTasks(merge(snapshot()));

    expect(tasks.find((t) => t.id === "PROJ-1")!.openDeps).toBe(1);
    expect(tasks.find((t) => t.id === "PROJ-2")!.openDeps).toBe(0);
  });

  it("mark a Ready task whose last Board move was out of Waiting as released, whatever machine last placed it", () => {
    const snap = snapshot();
    snap.flows[0].agents.push(
      agent("PROJ-5", "ready", { previous: "waiting" }), agent("PROJ-6", "ready", { previous: "review" }),
      agent("PROJ-7", "ready"), agent("PROJ-8", "in_progress", { previous: "waiting" }),
    );
    snap.flows[1].agents.push(agent("PROJ-5", "pr_opened", { task: "PROJ-5", active: 400 }));
    const released = Object.fromEntries(kanbanTasks(merge(snap)).map((t) => [t.id, t.released]));

    expect(released).toMatchObject({ "PROJ-5": true, "PROJ-6": false, "PROJ-7": false, "PROJ-8": false });
    expect(kanbanTasks(merge(snap)).find((t) => t.id === "PROJ-5")!.live).toMatchObject({ machine: "in-progress", state: "pr_opened" });
  });

  it("carry when the task entered its column, and 0 when the snapshot gives no time", () => {
    const snap = snapshot();
    snap.flows[0].agents[0].entered = 450;
    const tasks = kanbanTasks(merge(snap));

    expect([tasks.find((t) => t.id === "PROJ-1")!.entered, tasks.find((t) => t.id === "PROJ-2")!.entered]).toEqual([450, 0]);
  });

  it("have no milestone, pull requests or machine when the snapshot names none", () => {
    expect(kanbanTasks(merge(snapshot())).find((t) => t.id === "PROJ-2")).toMatchObject({ milestone: "", prs: [], live: null });
  });

  it("refreshes every card field the full record carries immediately after a successful save", () => {
    const before = kanbanTasks(merge(snapshot())).find((t) => t.id === "PROJ-1")!;
    const record: TaskRecord = {
      title: "Saved title", profile: "@bob", priority: "Low", labels: ["saved"], milestone: "m-99", dependencies: ["PROJ-8"],
      description: "Saved description", plan: "plan", notes: "notes", acceptanceCriteria: [], definitionOfDone: [],
    };

    expect(applyTaskRecord(before, record)).toMatchObject({
      title: "Saved title", assignee: "@bob", labels: ["saved"], milestone: "m-99", dependencies: ["PROJ-8"], description: "Saved description",
    });
  });
});

describe("the filters", () => {
  const card = (id: string, title: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({ ...task(id, "ready"), title, ...extra });
  const tasks = [
    card("PROJ-2482", "Kanban filters", { labels: ["needs-human", "size-3"], assignee: "@alice", milestone: "m-12" }),
    card("PROJ-2483", "Guard verdict per move", { labels: ["size-5"], assignee: "@alice", milestone: "m-12" }),
    card("PROJ-9", "Human review of the needs list", { labels: ["kind-decide"], assignee: "@agent-deep-high", milestone: "m-9" }),
    card("PROJ-10", "Unowned chore", { labels: ["size-3"] }),
  ];
  const ids = (prefs: Partial<typeof NO_PREFS>) => view(tasks, { ...NO_PREFS, ...prefs }).columns.flatMap((c) => c.buckets.flatMap((b) => b.tasks.map((t) => t.id))).sort();

  it("show every task while nothing is set", () => {
    expect(ids({})).toEqual(["PROJ-10", "PROJ-2482", "PROJ-2483", "PROJ-9"]);
    expect(filtersActive(NO_PREFS)).toBe(false);
  });

  it("match a word against the id, the title and the labels, ignoring case", () => {
    expect(ids({ query: "2482" })).toEqual(["PROJ-2482"]);
    expect(ids({ query: "proj-10" })).toEqual(["PROJ-10"]);
    expect(ids({ query: "GUARD" })).toEqual(["PROJ-2483"]);
    expect(ids({ query: "size-3" })).toEqual(["PROJ-10", "PROJ-2482"]);
  });

  it("limit a label: word to labels, so a title that says the same word does not match", () => {
    expect(ids({ query: "needs" })).toEqual(["PROJ-2482", "PROJ-9"]);
    expect(ids({ query: "label:needs" })).toEqual(["PROJ-2482"]);
    expect(ids({ query: "label:Needs-Human" })).toEqual(["PROJ-2482"]);
  });

  it("need every word of the bar to match", () => {
    expect(ids({ query: "kanban label:size-3" })).toEqual(["PROJ-2482"]);
    expect(ids({ query: "kanban label:size-5" })).toEqual([]);
    expect(ids({ query: "  label:size-3   " })).toEqual(["PROJ-10", "PROJ-2482"]);
  });

  it("filter by assignee, with null for any and an empty string for unassigned", () => {
    expect(ids({ assignee: "@alice" })).toEqual(["PROJ-2482", "PROJ-2483"]);
    expect(ids({ assignee: "" })).toEqual(["PROJ-10"]);
    expect(ids({ assignee: null })).toHaveLength(4);
  });

  it("filter by milestone, with an empty string for No milestone", () => {
    expect(ids({ milestone: "m-12" })).toEqual(["PROJ-2482", "PROJ-2483"]);
    expect(ids({ milestone: "" })).toEqual(["PROJ-10"]);
  });

  it("combine the bar and both menus, and move the counts with them", () => {
    const prefs = { ...NO_PREFS, query: "label:size", assignee: "@alice", milestone: "m-12" };
    const v = view(tasks, prefs);

    expect(ids(prefs)).toEqual(["PROJ-2482", "PROJ-2483"]);
    expect([v.shown, v.total, v.open]).toEqual([2, 4, 2]);
    expect(filtersActive(prefs)).toBe(true);
  });

  it("apply to hidden items too: a hidden task stays out whatever the bar says", () => {
    expect(ids({ query: "2482", hiddenTasks: new Set(["PROJ-2482"]) })).toEqual([]);
  });

  it("list the assignees and milestones to choose from, busiest first, with unassigned and No milestone", () => {
    expect(assigneeOptions(tasks)).toEqual([
      { value: "@alice", count: 2 }, { value: "@agent-deep-high", count: 1 }, { value: "", count: 1 },
    ]);
    expect(milestoneOptions(tasks)).toEqual([{ value: "m-12", count: 2 }, { value: "m-9", count: 1 }, { value: "", count: 1 }]);
  });
});

describe("label suggestions", () => {
  const labelled = (id: string, labels: string[]): KanbanTask => ({ ...task(id, "ready"), labels });
  const tasks = [labelled("PROJ-1", ["needs-human", "size-3"]), labelled("PROJ-2", ["needs-human"]), labelled("PROJ-3", ["adr-needed", "size-3"])];

  it("offer the labels that contain the word being typed, most used first, with their counts", () => {
    expect(labelSuggestions(tasks, "need")).toEqual([{ label: "needs-human", count: 2 }, { label: "adr-needed", count: 1 }]);
    expect(labelSuggestions(tasks, "kanban need")).toEqual([{ label: "needs-human", count: 2 }, { label: "adr-needed", count: 1 }]);
  });

  it("read the word after label: and offer nothing for an empty or finished word", () => {
    expect(labelSuggestions(tasks, "label:size")).toEqual([{ label: "size-3", count: 2 }]);
    expect(labelSuggestions(tasks, "")).toEqual([]);
    expect(labelSuggestions(tasks, "need ")).toEqual([]);
    expect(labelSuggestions(tasks, "zzz")).toEqual([]);
  });

  it("write label:<name> in place of the word being typed, ready for the next word", () => {
    expect(applySuggestion("need", "needs-human")).toBe("label:needs-human ");
    expect(applySuggestion("kanban label:si", "size-3")).toBe("kanban label:size-3 ");
  });
});

describe("what holds the Waiting lane", () => {
  const dep = (id: string, lane: string, ...dependencies: string[]): KanbanTask => {
    const open = dependencies.filter((d) => !d.startsWith("DONE")).length;
    return { ...task(id, lane), dependencies, openDeps: open };
  };
  // A gate in Review holds a Waiting hub, which holds two Waiting slices; one slice also waits on a Ready task
  const board = [
    dep("GATE", "review"), dep("HUB", "waiting", "GATE"), dep("S1", "waiting", "HUB"), dep("S2", "waiting", "HUB", "SIDE"),
    dep("SIDE", "ready"), dep("TIMED", "waiting"), dep("FREE", "waiting", "DONE-1"), dep("LATE", "in_progress", "GATE"), task("DONE-1", "done"),
  ];

  it("count every Waiting task behind a task, through other Waiting tasks, once each", () => {
    const counts = holdCounts(board);

    expect(counts.get("GATE")).toBe(3);
    expect(counts.get("HUB")).toBe(2);
    expect(counts.get("SIDE")).toBe(1);
    expect(counts.get("S1") ?? 0).toBe(0);
  });

  it("leave out a dependent that is not Waiting and a dependency that is Done", () => {
    const counts = holdCounts(board);

    expect(counts.get("DONE-1") ?? 0).toBe(0);
    expect(counts.get("TIMED") ?? 0).toBe(0);
  });

  it("rank the tasks at the bottom of the chains, most held first, leaving out a Waiting task that waits on open work", () => {
    expect(holders(board).map((h) => [h.task.id, h.holds])).toEqual([["GATE", 3], ["SIDE", 1]]);
  });

  it("count a Waiting task held only by its own Start Criteria as a holder of the tasks behind it", () => {
    const timed = [dep("TIMED", "waiting"), dep("AFTER", "waiting", "TIMED")];

    expect(holders(timed).map((h) => [h.task.id, h.holds])).toEqual([["TIMED", 1]]);
  });

  it("trace a task's chain: the Waiting tasks it holds and the open tasks it waits on, both transitively", () => {
    expect(chainOf(board, "HUB")).toEqual({ holds: new Set(["S1", "S2"]), waitsOn: new Set(["GATE"]) });
    expect(chainOf(board, "S2")).toEqual({ holds: new Set(), waitsOn: new Set(["HUB", "SIDE", "GATE"]) });
    expect(chainOf(board, "TIMED")).toEqual({ holds: new Set(), waitsOn: new Set() });
  });

  it("stop at a dependency cycle instead of counting forever", () => {
    const cycle = [dep("A", "waiting", "B"), dep("B", "waiting", "A")];

    expect(holdCounts(cycle).get("A")).toBe(1);
    expect(holders(cycle)).toEqual([]);
  });
});

describe("why a task the Recent rail points at has no card in view", () => {
  const tasks = [task("PROJ-1", "ready", "m-12"), task("PROJ-2", "ready", "m-9"), task("PROJ-3", "archived")];
  const why = (id: string, prefs: Partial<typeof NO_PREFS> = {}) => whyHidden(tasks, NAMES, { ...NO_PREFS, ...prefs }, id);

  it("is nothing for a card the board draws", () => {
    expect(why("PROJ-1")).toBeNull();
  });

  it("names a hidden task, a hidden milestone, the filters and a folded milestone, in that order", () => {
    expect(why("PROJ-1", { hiddenTasks: new Set(["PROJ-1"]), hiddenMilestones: new Set(["m-12"]) })).toBe("hidden");
    expect(why("PROJ-1", { hiddenMilestones: new Set(["m-12"]), query: "nothing" })).toBe("its milestone is hidden");
    expect(why("PROJ-1", { query: "nothing", folded: new Set(["m-12"]) })).toBe("filtered out");
    expect(why("PROJ-1", { assignee: "@bob" })).toBe("filtered out");
    expect(why("PROJ-1", { folded: new Set(["m-12"]) })).toBe("in a folded milestone");
  });

  it("says a task off every column, or off the board, has no card", () => {
    expect(why("PROJ-3")).toBe("not on the board");
    expect(why("PROJ-404")).toBe("not on the board");
  });
});

describe("Waiting stacks", () => {
  const wait = (id: string, milestone: string, ...dependencies: string[]): KanbanTask => ({ ...task(id, "waiting", milestone), dependencies, openDeps: dependencies.length });
  const waiting = (tasks: KanbanTask[], prefs = NO_PREFS) => column(view(tasks, prefs), "waiting").buckets;
  const stacks = (tasks: KanbanTask[], prefs = NO_PREFS) => waiting(tasks, prefs).flatMap((b) => b.stacks.map((s) => s.members.map((t) => t.id)));

  it("fold a Waiting task under the Waiting dependency in its bucket, the rest in chain depth then id order", () => {
    // a four-deep chain, entered out of order, with a sibling slice beside the second link
    const tasks = [wait("T-5", "m-1", "T-3"), wait("T-3", "m-1", "T-2"), wait("T-4", "m-1", "T-2"), wait("T-2", "m-1", "T-1"), wait("T-1", "m-1")];

    expect(stacks(tasks)).toEqual([["T-1", "T-2", "T-3", "T-4", "T-5"]]);
    expect(waiting(tasks)[0].stacks[0].top.id).toBe("T-1");
  });

  it("order ids by number, not text", () => {
    expect(stacks([wait("T-10", "m-1", "T-1"), wait("T-9", "m-1", "T-1"), wait("T-1", "m-1")])).toEqual([["T-1", "T-9", "T-10"]]);
  });

  it("stack a task with two Waiting blockers under the one that unblocks first, lowest chain depth then id, and name both on its card", () => {
    // T-4 waits on T-3 (depth 0) and T-2 (depth 1); T-5 waits on T-3 and T-1, both depth 0
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-1", "T-1"), wait("T-3", "m-1"), wait("T-4", "m-1", "T-2", "T-3"), wait("T-5", "m-1", "T-3", "T-1")];
    const bucket = waiting(tasks)[0];

    expect(stacks(tasks)).toEqual([["T-3", "T-4"], ["T-1", "T-2", "T-5"]]);
    expect(bucket.stacks[0].links.get("T-4")).toEqual(["T-2", "T-3"]);
    expect(bucket.stacks[1].links.get("T-5")).toEqual(["T-3", "T-1"]);
  });

  it("leave a task whose only open dependency is not Waiting, or is in another milestone, a stack of its own", () => {
    const tasks = [wait("T-1", "m-1", "R-1"), { ...task("R-1", "ready", "m-1") }, wait("T-2", "m-2", "T-3"), wait("T-3", "m-3")];

    expect(stacks(tasks)).toEqual([["T-3"], ["T-2"], ["T-1"]]);
  });

  it("build stacks from the visible cards, so a filtered-out or hidden task leaves its stack", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-1", "T-1"), wait("T-3", "m-1", "T-2")];

    expect(stacks(tasks, hideTask(NO_PREFS, "T-2"))).toEqual([["T-3"], ["T-1"]]);
    expect(stacks(tasks, { ...NO_PREFS, query: "T-3" })).toEqual([["T-3"]]);
  });

  it("re-form when a member moves out of Waiting, and leave the other lanes unstacked", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-1", "T-1"), wait("T-3", "m-1", "T-2")];
    const moved = tasks.map((t) => (t.id === "T-2" ? { ...t, lane: "ready" } : t));

    expect(stacks(moved)).toEqual([["T-3"], ["T-1"]]);
    expect(column(view(moved), "ready").buckets[0].stacks).toEqual([]);
  });

  it("find the stack a task sits in, only when it has company", () => {
    const l = view([wait("T-1", "m-1"), wait("T-2", "m-1", "T-1"), wait("T-3", "m-1")]);

    expect(stackOf(l, "T-2")?.members.map((t) => t.id)).toEqual(["T-1", "T-2"]);
    expect(stackOf(l, "T-3")).toBeUndefined();
  });

  it("stop at a dependency cycle instead of recursing forever", () => {
    expect(stacks([wait("T-1", "m-1", "T-2"), wait("T-2", "m-1", "T-1")]).flat().sort()).toEqual(["T-1", "T-2"]);
  });
});

describe("Done chains", () => {
  const done = (id: string, milestone: string, ...dependencies: string[]): KanbanTask => ({ ...task(id, "done", milestone), dependencies });
  const finished = (tasks: KanbanTask[], prefs = NO_PREFS) => column(view(tasks, prefs), "done").buckets;
  const stacks = (tasks: KanbanTask[], prefs = NO_PREFS) => finished(tasks, prefs).flatMap((b) => b.stacks.map((s) => s.members.map((t) => t.id)));

  it("fold a Done task under the Done task that depends on it, the chain's last finished on top and the rest by distance from it", () => {
    // T-3 finished last: T-2 unblocked it, T-1 unblocked T-2, and T-4 sat beside T-2
    const tasks = [done("T-1", "m-1"), done("T-2", "m-1", "T-1"), done("T-4", "m-1", "T-1"), done("T-3", "m-1", "T-2", "T-4")];
    const bucket = finished(tasks)[0];

    expect(stacks(tasks)).toEqual([["T-3", "T-2", "T-4", "T-1"]]);
    expect(bucket.stacks[0].top.id).toBe("T-3");
    expect(bucket.stacks[0].links.get("T-1")).toEqual(["T-2", "T-4"]);
  });

  it("fold the tasks a milestone's retro depends on under the retro", () => {
    const tasks = [done("T-9", "m-1", "T-1", "T-2", "T-10"), done("T-10", "m-1"), done("T-1", "m-1"), done("T-2", "m-1")];

    expect(stacks(tasks)).toEqual([["T-9", "T-1", "T-2", "T-10"]]);
  });

  it("leave a Done task whose dependency is in another milestone, not Done or off the board a stack of its own", () => {
    const tasks = [done("T-1", "m-1", "T-2", "R-1", "X-1"), done("T-2", "m-2"), { ...task("R-1", "ready", "m-1") }];

    expect(stacks(tasks)).toEqual([["T-2"], ["T-1"]]);
  });

  it("build stacks from the visible cards, so a filtered-out or hidden task leaves its chain", () => {
    const tasks = [done("T-1", "m-1"), done("T-2", "m-1", "T-1"), done("T-3", "m-1", "T-2")];

    expect(stacks(tasks, hideTask(NO_PREFS, "T-2"))).toEqual([["T-3"], ["T-1"]]);
    expect(stacks(tasks, { ...NO_PREFS, query: "T-1" })).toEqual([["T-1"]]);
  });

  it("stack only the Waiting and Done lanes", () => {
    const tasks = [{ ...task("T-1", "review", "m-1") }, { ...task("T-2", "review", "m-1"), dependencies: ["T-1"] }];

    expect(column(view(tasks), "review").buckets[0].stacks).toEqual([]);
  });

  it("find the Done chain a task sits in, only when it has company", () => {
    const l = view([done("T-1", "m-1"), done("T-2", "m-1", "T-1"), done("T-3", "m-1")]);

    expect(stackOf(l, "T-1")?.members.map((t) => t.id)).toEqual(["T-2", "T-1"]);
    expect(stackOf(l, "T-3")).toBeUndefined();
  });

  it("stop at a dependency cycle instead of recursing forever", () => {
    expect(stacks([done("T-1", "m-1", "T-2"), done("T-2", "m-1", "T-1")]).flat().sort()).toEqual(["T-1", "T-2"]);
  });
});

describe("Waiting cards linked to a blocker in another milestone", () => {
  const wait = (id: string, milestone: string, ...dependencies: string[]): KanbanTask => ({ ...task(id, "waiting", milestone), dependencies, openDeps: dependencies.length });
  const cross = (tasks: KanbanTask[], prefs = NO_PREFS) => [...view(tasks, prefs).cross].map(([id, held]) => [id, held.map((t) => t.id)]);

  it("map a Waiting task to its Waiting dependencies in other milestones, which do not stack", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-2", "T-1"), wait("T-3", "m-2", "T-1")];

    expect(cross(tasks)).toEqual([["T-2", ["T-1"]], ["T-3", ["T-1"]]]);
    expect(column(view(tasks), "waiting").buckets.flatMap((b) => b.stacks).every((s) => s.members.length === 1)).toBe(true);
  });

  it("leave a same-milestone blocker to the stack, and a blocker that is not Waiting to the Held by strip", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-1", "T-1"), task("T-3", "in_progress", "m-2"), wait("T-4", "m-1", "T-3")];

    expect(cross(tasks)).toEqual([]);
  });

  it("link a stacked task to its other-milestone blocker too, and list every such blocker", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-2"), wait("T-3", "m-2", "T-2", "T-1"), wait("T-4", "m-3", "T-1", "T-2")];

    expect(cross(tasks)).toEqual([["T-3", ["T-1"]], ["T-4", ["T-1", "T-2"]]]);
    expect(stackOf(view(tasks), "T-3")?.members.map((t) => t.id)).toEqual(["T-2", "T-3"]);
  });

  it("draw only the visible blockers, so a hidden or filtered-out blocker leaves no link", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-2", "T-1")];

    expect(cross(tasks, hideTask(NO_PREFS, "T-1"))).toEqual([]);
    expect(cross(tasks, { ...NO_PREFS, query: "T-2" })).toEqual([]);
    expect(cross(tasks, { ...NO_PREFS, query: "T-1" })).toEqual([]);
  });

  it("follow a blocker that leaves Waiting, which is then no longer linked", () => {
    const tasks = [wait("T-1", "m-1"), wait("T-2", "m-2", "T-1")];

    expect(cross(tasks.map((t) => (t.id === "T-1" ? { ...t, lane: "ready" } : t)))).toEqual([]);
  });
});

describe("the milestone outline", () => {
  it("lists each open milestone with its done and total, largest first, and leaves out finished milestones and tasks with none", () => {
    const tasks = [
      task("T-1", "done", "m-1"), task("T-2", "ready", "m-1"),
      task("T-3", "done", "m-2"), task("T-4", "done", "m-2"),
      task("T-5", "ready", "m-3"), task("T-6", "review", "m-3"), task("T-7", "waiting", "m-3"),
      task("T-8", "ready", "m-4"), task("T-9", "done", "m-4"),
      task("T-10", "ready"),
    ];

    expect(milestoneOutline(tasks)).toEqual([
      { milestone: "m-3", done: 0, total: 3 },
      { milestone: "m-4", done: 1, total: 2 },
      { milestone: "m-1", done: 1, total: 2 },
    ]);
  });
});
