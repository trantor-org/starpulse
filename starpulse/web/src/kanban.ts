// The Kanban view's model: the Board's open tasks laid out as columns of milestone buckets. Pure, so the view only draws it.
import type { Sky } from "./sky";
import type { TaskRecord } from "./taskView";
import type { Pull } from "./types";

/** The Board states drawn as columns, in order. New is the creation pseudo-state and Completed and Archived have left the lanes. */
export const COLUMNS = ["ready", "waiting", "in_progress", "review", "needs_attention", "done"];

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
  live: { machine: string; state: string; at: number } | null;
  /** Ready again after waiting: its last Board move was out of Waiting, so a machine state from before it no longer describes the card. */
  released: boolean;
  /** The verdict on each Board column the task may move to, by state id; a column absent here has no transition. */
  moves: Record<string, { allowed: boolean; reason: string; skill: string }>;
  /** When the task entered its column, epoch seconds; 0 when the server gave no time. */
  entered: number;
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
const options = (tasks: KanbanTask[], of: (t: KanbanTask) => string, order: (a: Option, b: Option) => number): Option[] => {
  const counts = new Map<string, number>();
  for (const t of tasks.filter((x) => COLUMNS.includes(x.lane))) counts.set(of(t), (counts.get(of(t)) ?? 0) + 1);
  return [...counts].map(([value, count]) => ({ value, count })).sort(order);
};
/** Busiest first, the unassigned after the named. */
export const assigneeOptions = (tasks: KanbanTask[]) =>
  options(tasks, (t) => t.assignee, (a, b) => Number(a.value === "") - Number(b.value === "") || b.count - a.count || a.value.localeCompare(b.value));
/** Newest first, as the buckets run, with No milestone last. */
export const milestoneOptions = (tasks: KanbanTask[]) => options(tasks, (t) => t.milestone, (a, b) => milestoneNumber(b.value) - milestoneNumber(a.value));

/** The labels containing the word being typed (the last word of the bar, after a `label:` prefix), most used first. */
export function labelSuggestions(tasks: KanbanTask[], query: string): { label: string; count: number }[] {
  const word = /\S+$/.exec(query)?.[0].toLowerCase().replace(LABEL, "") ?? "";
  if (!word) return [];
  const counts = new Map<string, number>();
  for (const t of tasks.filter((x) => COLUMNS.includes(x.lane))) for (const l of t.labels) counts.set(l, (counts.get(l) ?? 0) + 1);
  return [...counts].filter(([l]) => l.toLowerCase().includes(word)).map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
/** The bar with the word being typed written as `label:<name>`, ready for the next word. */
export const applySuggestion = (query: string, label: string) => `${query.replace(/\S*$/, "")}${LABEL}${label} `;

export interface Bucket {
  milestone: string;
  tasks: KanbanTask[];
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

export function layout(tasks: KanbanTask[], names: Record<string, string>, prefs: Prefs): Layout {
  const drawn = tasks.filter((t) => COLUMNS.includes(t.lane));
  const visible = drawn.filter(
    (t) => !prefs.hiddenTasks.has(t.id) && !prefs.hiddenMilestones.has(t.milestone) && matches(t, prefs.query)
      && (prefs.assignee === null || t.assignee === prefs.assignee) && (prefs.milestone === null || t.milestone === prefs.milestone),
  );
  const columns = COLUMNS.map((id): Column => {
    const here = visible.filter((t) => t.lane === id).sort((a, b) => b.entered - a.entered || b.id.localeCompare(a.id, undefined, { numeric: true }));
    const keys = [...new Set(here.map((t) => t.milestone))].sort((a, b) => milestoneNumber(b) - milestoneNumber(a));
    const buckets = keys.map((milestone) => ({ milestone, tasks: here.filter((t) => t.milestone === milestone), folded: prefs.folded.has(milestone) }));
    return { id, name: names[id] ?? id, count: here.length, buckets };
  });
  const done = columns.find((c) => c.id === "done")?.count ?? 0;
  return {
    columns, open: visible.length - done, done, shown: visible.length, total: drawn.length,
    hidden: prefs.hiddenMilestones.size + prefs.hiddenTasks.size,
  };
}

/** The Board's tasks as cards: its own fields, the pull requests the server read for it and the machine that last placed it. */
export function kanbanTasks(sky: Sky): KanbanTask[] {
  const open = new Set(sky.board.agents.filter((a) => a.state !== "done").map((a) => a.id));
  return sky.board.agents.map((a) => {
    const latest = sky.latest[a.id], dependencies = a.dependencies ?? [];
    return {
      id: a.id, title: a.title, lane: a.state, milestone: a.milestone ?? "", labels: a.labels ?? [], assignee: a.model, dependencies,
      openDeps: dependencies.filter((d) => open.has(d)).length, prs: sky.pulls[a.id] ?? [], description: a.description ?? "",
      live: latest ? { machine: latest.flow, state: latest.state, at: latest.at } : null,
      released: a.state === "ready" && a.previous === "waiting", moves: a.moves ?? {}, entered: a.entered ?? 0,
    };
  });
}
