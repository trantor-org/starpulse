import { describe, expect, it } from "vitest";
import { NO_PREFS, applySuggestion, applyTaskRecord, assigneeOptions, filtersActive, hideMilestone, hideTask, kanbanTasks, labelSuggestions, layout, milestoneOptions, show, showAll, toggleFold, type KanbanTask } from "./kanban";
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
  const pull = (number: number, checks: Pull["checks"], threads = 0): Pull => ({ number, url: `https://github.com/o/r/pull/${number}`, checks, merged: false, threads, stale: false });
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
    settled: { "PROJ-4": "completed" },
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
