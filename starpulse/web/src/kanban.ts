// The Kanban view's model: the Board's open tasks laid out as columns of milestone buckets. Pure, so the view only draws it.
import type { Sky } from "./sky";
import type { TaskRecord } from "./taskView";
import type { Pull, TrailStep } from "./types";

/** The Board states drawn as columns, in order. New is the creation pseudo-state and Completed and Archived have left the lanes. */
export const COLUMNS = ["ready", "waiting", "in_progress", "review", "needs_attention", "done"];

/** The lanes drawn as columns: the board's own lanes in order (StarPulse's native board, a Backlog.md project's statuses), except those six on a board with the `ready` lane (trantor's lifecycle) and before the board's lanes are known. */
export const columnsOf = (names: Record<string, string>): string[] => ("ready" in names || !Object.keys(names).length ? COLUMNS : Object.keys(names));

export interface KanbanTask {
  id: string;
  title: string;
  lane: string;
  /** The milestone key the snapshot carries (`m-76`); empty when the task has none. */
  milestone: string;
  labels: string[];
  /** The agent profile that holds the task; empty when unassigned. */
  assignee: string;
  dependencies: string[];
  /** Dependencies still on the Board and not Done. */
  openDeps: number;
  prs: Pull[];
  description: string;
  /** The lifecycle machine that last placed the task, the state it left it in and when (epoch seconds). */
  live: { machine: string; state: string; at: number; source?: string } | null;
  /** Ready again after waiting: its last Board move was out of Waiting, so a machine state from before it no longer describes the card. */
  released: boolean;
  /** The verdict on each Board column the task may move to, by state id; a column absent here has no transition. */
  moves: Record<string, { allowed: boolean; reason: string; skill: string }>;
  /** When the task entered its column, epoch seconds; 0 when the server gave no time. */
  entered: number;
  /** When the task was created, epoch seconds; null when the board does not say. */
  created: number | null;
  /** Every lifecycle machine the task is in: its state there, when it last moved, the machine's third-party source and its trail. */
  machines: { machine: string; state: string; at: number; source?: string; trail: TrailStep[] }[];
}

/** Refresh the snapshot-sized card with the fields a successful full-record edit can change. */
export const applyTaskRecord = (task: KanbanTask, record: TaskRecord): KanbanTask => ({
  ...task,
  title: record.title,
  assignee: record.profile,
  labels: record.labels,
  milestone: record.milestone,
  dependencies: record.dependencies,
  description: record.description,
});

/** What the operator chose to filter, fold or hide; each change returns a new value. */
export interface Prefs {
  /** The search bar's text: words matched against id, title and labels, `label:<name>` against labels alone. */
  query: string;
  /** The profile to show; null shows any and an empty string shows the unassigned. */
  assignee: string | null;
  /** The milestone key to show; null shows any and an empty string shows the tasks with none. */
  milestone: string | null;
  folded: ReadonlySet<string>;
  hiddenMilestones: ReadonlySet<string>;
  hiddenTasks: ReadonlySet<string>;
}
export const NO_PREFS: Prefs = { query: "", assignee: null, milestone: null, folded: new Set(), hiddenMilestones: new Set(), hiddenTasks: new Set() };

const flip = (s: ReadonlySet<string>, key: string) => {
  const n = new Set(s);
  if (!n.delete(key)) n.add(key);
  return n;
};
const added = (s: ReadonlySet<string>, key: string) => new Set(s).add(key);
const dropped = (s: ReadonlySet<string>, key: string) => {
  const n = new Set(s);
  n.delete(key);
  return n;
};

/** A milestone folds in every column at once. */
export const toggleFold = (p: Prefs, milestone: string): Prefs => ({ ...p, folded: flip(p.folded, milestone) });
export const hideMilestone = (p: Prefs, milestone: string): Prefs => ({ ...p, hiddenMilestones: added(p.hiddenMilestones, milestone) });
export const hideTask = (p: Prefs, id: string): Prefs => ({ ...p, hiddenTasks: added(p.hiddenTasks, id) });
export const show = (p: Prefs, kind: "milestone" | "task", key: string): Prefs =>
  kind === "milestone" ? { ...p, hiddenMilestones: dropped(p.hiddenMilestones, key) } : { ...p, hiddenTasks: dropped(p.hiddenTasks, key) };
/** Everything hidden comes back; folds stay as they are. */
export const showAll = (p: Prefs): Prefs => ({ ...p, hiddenMilestones: new Set(), hiddenTasks: new Set() });

export const filtersActive = (p: Prefs) => p.query.trim() !== "" || p.assignee !== null || p.milestone !== null;
export const clearFilters = (p: Prefs): Prefs => ({ ...p, query: "", assignee: null, milestone: null });

const LABEL = "label:";
const words = (query: string) => query.toLowerCase().split(/\s+/).filter(Boolean);

/** Whether a task answers every word of the bar: a plain word is a substring of its id, title or a label, a `label:` word of a label alone. */
const matches = (t: KanbanTask, query: string) =>
  words(query).every((w) => {
    if (!w.startsWith(LABEL)) return [t.id, t.title, ...t.labels].some((f) => f.toLowerCase().includes(w));
    const name = w.slice(LABEL.length);
    return t.labels.some((l) => l.toLowerCase().includes(name));
  });

/** What a filter menu lists: each value the drawn tasks carry and how many carry it. */
export interface Option {
  value: string;
  count: number;
}
const options = (tasks: KanbanTask[], columns: string[], of: (t: KanbanTask) => string, order: (a: Option, b: Option) => number): Option[] => {
  const counts = new Map<string, number>();
  for (const t of tasks.filter((x) => columns.includes(x.lane))) counts.set(of(t), (counts.get(of(t)) ?? 0) + 1);
  return [...counts].map(([value, count]) => ({ value, count })).sort(order);
};
/** Busiest first, the unassigned after the named. */
export const assigneeOptions = (tasks: KanbanTask[], columns = COLUMNS) =>
  options(tasks, columns, (t) => t.assignee, (a, b) => Number(a.value === "") - Number(b.value === "") || b.count - a.count || a.value.localeCompare(b.value));
/** Newest first, as the buckets run, with No milestone last. */
export const milestoneOptions = (tasks: KanbanTask[], columns = COLUMNS) => options(tasks, columns, (t) => t.milestone, (a, b) => milestoneNumber(b.value) - milestoneNumber(a.value));

/** One open milestone of the navigator's outline: how many of its tasks are done. */
export interface Outline {
  milestone: string;
  done: number;
  total: number;
}
/** The milestones with a task not Done, largest first and newest among equals; tasks with no milestone have no row. */
export function milestoneOutline(tasks: KanbanTask[]): Outline[] {
  const counts = new Map<string, Outline>();
  for (const t of tasks.filter((x) => x.milestone)) {
    const row = counts.get(t.milestone) ?? { milestone: t.milestone, done: 0, total: 0 };
    row.total++;
    if (t.lane === "done") row.done++;
    counts.set(t.milestone, row);
  }
  return [...counts.values()].filter((r) => r.done < r.total).sort((a, b) => b.total - a.total || milestoneNumber(b.milestone) - milestoneNumber(a.milestone));
}

/** The labels containing the word being typed (the last word of the bar, after a `label:` prefix), most used first. */
export function labelSuggestions(tasks: KanbanTask[], query: string, columns = COLUMNS): { label: string; count: number }[] {
  const word = /\S+$/.exec(query)?.[0].toLowerCase().replace(LABEL, "") ?? "";
  if (!word) return [];
  const counts = new Map<string, number>();
  for (const t of tasks.filter((x) => columns.includes(x.lane))) for (const l of t.labels) counts.set(l, (counts.get(l) ?? 0) + 1);
  return [...counts].filter(([l]) => l.toLowerCase().includes(word)).map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
/** The bar with the word being typed written as `label:<name>`, ready for the next word. */
export const applySuggestion = (query: string, label: string) => `${query.replace(/\S*$/, "")}${LABEL}${label} `;

/**
 * Tasks of one bucket folded along their dependency chains. A Waiting stack's top waits on nothing else Waiting in the bucket and the rest
 * sit under it in unblock order; a Done chain runs the other way, its top the last finished, which nothing else Done in the bucket depends on.
 */
export interface Stack {
  top: KanbanTask;
  /** The top first, then the rest by chain depth, then id. */
  members: KanbanTask[];
  /** Each member's neighbours toward the top, id-ordered in a Done chain: the Waiting dependencies it waits on, or the Done tasks it unblocked, in the bucket. */
  links: ReadonlyMap<string, string[]>;
}
export interface Bucket {
  milestone: string;
  tasks: KanbanTask[];
  /** The Waiting and Done lanes' tasks folded into stacks, in the order their tops sit in `tasks`; empty in every other lane. */
  stacks: Stack[];
  folded: boolean;
}
export interface Column {
  id: string;
  name: string;
  /** Visible tasks, those inside a folded bucket included. */
  count: number;
  buckets: Bucket[];
}
export interface Layout {
  columns: Column[];
  /** The Waiting blockers in other milestones of each Waiting task that has any, by task id. */
  cross: ReadonlyMap<string, KanbanTask[]>;
  /** Visible tasks outside the Done column, and in it. */
  open: number;
  done: number;
  shown: number;
  /** Every task a column could draw, hidden or not. */
  total: number;
  /** Hidden milestones and tasks. */
  hidden: number;
}

/** The number in a key like `m-76`; a task with no milestone sorts below every one. */
const milestoneNumber = (milestone: string) => (milestone ? Number(/^m-(\d+)/.exec(milestone)?.[1] ?? 0) : -1);

/** Whether a task passes the search bar and the profile and milestone filters. */
const filtered = (t: KanbanTask, prefs: Prefs) =>
  matches(t, prefs.query) && (prefs.assignee === null || t.assignee === prefs.assignee) && (prefs.milestone === null || t.milestone === prefs.milestone);

const byId = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

/** The lanes whose tasks fold into stacks. */
export const STACKED = ["waiting", "done"];

/**
 * A bucket's tasks of one lane as stacks. A Waiting task folds under its first blocker: of its Waiting dependencies in the bucket, the one
 * that unblocks first (lowest chain depth, then id). A Done task folds the other way, under the Done task that depends on it, so the chain's
 * last finished sits on top. A dependency in another milestone, or in another lane, does not stack.
 */
export function stacksOf(tasks: KanbanTask[], lane = "waiting"): Stack[] {
  const here = new Map(tasks.map((t) => [t.id, t]));
  const links = new Map(tasks.map((t) => [t.id, [] as string[]]));
  for (const t of tasks) {
    for (const d of t.dependencies) {
      if (d === t.id || !here.has(d)) continue;
      if (lane === "done") links.get(d)!.push(t.id);
      else links.get(t.id)!.push(d);
    }
  }
  if (lane === "done") for (const l of links.values()) l.sort(byId);
  const depth = new Map<string, number>();
  // a cycle stops counting where it closes
  const depthOf = (id: string, path: string[] = []): number => {
    if (path.includes(id)) return 0;
    let d = depth.get(id);
    if (d === undefined) depth.set(id, d = Math.max(-1, ...links.get(id)!.map((x) => depthOf(x, [...path, id]))) + 1);
    return d;
  };
  const first = (id: string) => [...links.get(id)!].sort((a, b) => depthOf(a) - depthOf(b) || byId(a, b))[0];
  const rootOf = (id: string, path: string[] = []): string => {
    const f = path.includes(id) ? undefined : first(id);
    return f === undefined ? id : rootOf(f, [...path, id]);
  };
  const roots = new Map(tasks.map((t) => [t.id, rootOf(t.id)]));
  return tasks.filter((t) => roots.get(t.id) === t.id).map((top) => ({
    top,
    members: tasks.filter((t) => roots.get(t.id) === top.id).sort((a, b) => depthOf(a.id) - depthOf(b.id) || byId(a.id, b.id)),
    links,
  }));
}

/** Each Waiting task's Waiting dependencies in other milestones, among `visible` cards: they cannot stack, so the card links to each instead. */
export function crossOf(visible: KanbanTask[]): Map<string, KanbanTask[]> {
  const waiting = new Map(visible.filter((t) => t.lane === "waiting").map((t) => [t.id, t]));
  const cross = new Map<string, KanbanTask[]>();
  for (const t of waiting.values()) {
    const held = t.dependencies.map((d) => waiting.get(d)).filter((d): d is KanbanTask => d !== undefined && d.milestone !== t.milestone);
    if (held.length) cross.set(t.id, held);
  }
  return cross;
}

/** What holds a stack unstacked: the pointer over it or focus inside it. Escape drops both, so it folds under a pointer that has not left. */
export interface StackOpen { hover: boolean; focus: boolean }
export type StackEvent = "enter" | "leave" | "focus" | "blur" | "escape";
export const CLOSED: StackOpen = { hover: false, focus: false };
export const stackStep = (s: StackOpen, e: StackEvent): StackOpen =>
  e === "escape" ? CLOSED : e === "enter" || e === "leave" ? { ...s, hover: e === "enter" } : { ...s, focus: e === "focus" };
export const unstacked = (s: StackOpen) => s.hover || s.focus;

/** The stack a task sits in, when it has company. */
export const stackOf = (l: Layout, id: string): Stack | undefined =>
  l.columns.flatMap((c) => c.buckets).flatMap((b) => b.stacks).find((s) => s.members.length > 1 && s.members.some((t) => t.id === id));

export function layout(tasks: KanbanTask[], names: Record<string, string>, prefs: Prefs): Layout {
  const lanes = columnsOf(names);
  const drawn = tasks.filter((t) => lanes.includes(t.lane));
  const visible = drawn.filter(
(t) => !prefs.hiddenTasks.has(t.id) && !prefs.hiddenMilestones.has(t.milestone) && filtered(t, prefs));
  const columns = lanes.map((id): Column => {
    const here = visible.filter((t) => t.lane === id).sort((a, b) => b.entered - a.entered || b.id.localeCompare(a.id, undefined, { numeric: true }));
    const keys = [...new Set(here.map((t) => t.milestone))].sort((a, b) => milestoneNumber(b) - milestoneNumber(a));
    const buckets = keys.map((milestone): Bucket => {
      const inBucket = here.filter((t) => t.milestone === milestone);
      return { milestone, tasks: inBucket, stacks: STACKED.includes(id) ? stacksOf(inBucket, id) : [], folded: prefs.folded.has(milestone) };
    });
    return { id, name: names[id] ?? id, count: here.length, buckets };
  });
  const done = columns.find((c) => c.id === "done")?.count ?? 0;
  return {
    columns, cross: crossOf(visible), open: visible.length - done, done, shown: visible.length, total: drawn.length,
    hidden: prefs.hiddenMilestones.size + prefs.hiddenTasks.size,
  };
}

/** Why task `id` has no card in view: hidden, its milestone hidden, filtered out or folded away; null when its card is drawn. */
export function whyHidden(tasks: KanbanTask[], names: Record<string, string>, prefs: Prefs, id: string): string | null {
  const t = tasks.find((x) => x.id === id);
  if (!t || !columnsOf(names).includes(t.lane)) return "not on the board";
  if (prefs.hiddenTasks.has(id)) return "hidden";
  if (prefs.hiddenMilestones.has(t.milestone)) return "its milestone is hidden";
  if (!filtered(t, prefs)) return "filtered out";
  return prefs.folded.has(t.milestone) ? "in a folded milestone" : null;
}

/** Each pull request a task cites, as GitHub was last read for it; one not read yet is drawn unread (`stale`) rather than left off. */
const cited = (urls: string[], read: Pull[]): Pull[] => {
  const unread = urls.filter((url) => !read.some((p) => p.url === url));
  return [...read, ...unread.map((url) => ({ number: Number(/(\d+)\/?$/.exec(url)?.[1] ?? 0), url, checks: "none" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: true }))];
};

/** The Board's tasks as cards: its own fields, the pull requests the server read for it and the machine that last placed it. */
export function kanbanTasks(sky: Sky): KanbanTask[] {
  const open = new Set(sky.board.agents.filter((a) => a.state !== "done").map((a) => a.id));
  return sky.board.agents.map((a) => {
    const latest = sky.latest[a.id], dependencies = a.dependencies ?? [];
    return {
      id: a.id, title: a.title, lane: a.state, milestone: a.milestone ?? "", labels: a.labels ?? [], assignee: a.model, dependencies,
      openDeps: dependencies.filter((d) => open.has(d)).length, prs: cited(a.prs ?? [], sky.pulls[a.id] ?? []), description: a.description ?? "",
      live: latest ? { machine: latest.flow, state: latest.state, at: latest.at, source: sky.flows[latest.flow]?.machine.source } : null,
      released: a.state === "ready" && a.previous === "waiting", moves: a.moves ?? {}, entered: a.entered ?? 0, created: a.created ?? null,
      machines: Object.values(sky.flows).filter((f) => f.name !== "board").flatMap((f) => f.agents.filter((m) => m.task === a.id)
        .map((m) => ({ machine: f.name, state: m.state, at: m.active ?? 0, source: f.machine.source, trail: m.trail ?? [] }))),
    };
  });
}

/** The dependency edges between open tasks: each task's open dependencies, and each task's Waiting dependents. */
function edges(tasks: KanbanTask[]) {
  const open = new Set(tasks.filter((t) => t.lane !== "done").map((t) => t.id));
  const waitsOn = new Map<string, string[]>(), heldBy = new Map<string, string[]>();
  for (const t of tasks) {
    const deps = t.dependencies.filter((d) => open.has(d));
    if (t.lane === "done" || !deps.length) continue;
    waitsOn.set(t.id, deps);
    if (t.lane === "waiting") for (const d of deps) heldBy.set(d, [...(heldBy.get(d) ?? []), t.id]);
  }
  return { waitsOn, heldBy };
}

/** Every task reachable from `id` along `next`, `id` itself left out, each once. */
function reach(id: string, next: Map<string, string[]>): Set<string> {
  const seen = new Set<string>(), todo = [id];
  for (let at = todo.pop(); at !== undefined; at = todo.pop()) {
    for (const n of next.get(at) ?? []) {
      if (n === id || seen.has(n)) continue;
      seen.add(n);
      todo.push(n);
    }
  }
  return seen;
}

/** A task's chain: the Waiting tasks it holds and the open tasks it waits on, both transitively. */
export function chainOf(tasks: KanbanTask[], id: string): { holds: Set<string>; waitsOn: Set<string> } {
  const e = edges(tasks);
  return { holds: reach(id, e.heldBy), waitsOn: reach(id, e.waitsOn) };
}

/** How many Waiting tasks each task holds: those that depend on it while it is not Done, directly or through other Waiting tasks, each counted once. */
export function holdCounts(tasks: KanbanTask[]): Map<string, number> {
  const { heldBy } = edges(tasks);
  return new Map([...heldBy.keys()].map((id) => [id, reach(id, heldBy).size]));
}

/** The tasks at the bottom of the Waiting chains, most held first: each holds Waiting work and is not itself waiting on open work. */
export function holders(tasks: KanbanTask[], counts = holdCounts(tasks)): { task: KanbanTask; holds: number }[] {
  return tasks
    .filter((t) => (counts.get(t.id) ?? 0) > 0 && !(t.lane === "waiting" && t.openDeps > 0))
    .map((task) => ({ task, holds: counts.get(task.id)! }))
    .sort((a, b) => b.holds - a.holds || a.task.id.localeCompare(b.task.id, undefined, { numeric: true }));
}
