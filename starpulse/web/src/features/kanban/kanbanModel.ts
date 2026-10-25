// The Kanban view's model: the Board's open tasks laid out as columns of milestone buckets. Pure, so the view only draws it.
import { midnight, type Sky } from "../../render/sky";
import type { TaskRecord } from "./taskViewModel";
import type { Option } from "../../shared/ChoiceMenu";
import type { ClaimRelease, Move, Pull, Rating, Roles, TrailStep } from "../../api";
import { ago } from "../../shared/clock";
import { sessionNickname } from "./nickname";

/** The States the machine gives a lifecycle role, keyed by role, in column order. The creation and final States have left the lanes. */
const lifecycleStates = ({ ready, waiting, working, review, attention, done }: Roles) => ({ ready, waiting, working, review, attention, done });

/** The role a State plays in the lifecycle columns, when it plays one. */
export const roleOf = (roles: Roles, state: string): string | undefined => Object.entries(lifecycleStates(roles)).find(([, s]) => s === state)?.[0];

/** The tasks a column may draw: every task, except a Done one that entered before the local midnight of `now`'s day. A Done task the snapshot gave no time for (`entered` 0) is drawn. */
export const recent = (tasks: KanbanTask[], now: number, roles: Roles): KanbanTask[] =>
  tasks.filter((t) => t.lane !== roles.done || !t.entered || t.entered >= midnight(new Date(now * 1000)));

/** The lanes drawn as columns: the machine's lifecycle States in order when it names a ready State (trantor's lifecycle), else the board's own lanes in order (StarPulse's native board, a Backlog.md project's statuses); none before the lanes are known. */
export const columnsOf = (names: Record<string, string>, roles: Roles): string[] => {
  const states = new Set(Object.values(lifecycleStates(roles)).filter((s): s is string => !!s));
  return roles.ready ? [...states] : Object.keys(names);
};

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
  /** The scheduler runs whose run id names the task, each linked to the run's page. */
  runs?: { url: string; status: string; startedAt: string }[];
  description: string;
  /** The lifecycle machine that last placed the task, the state it left it in and when (epoch seconds). */
  live: { machine: string; state: string; at: number; source?: string | null } | null;
  /** The pass/fail verdict on the task, drawn in the task view only; absent when it was never rated or the rating was cleared. */
  rating?: Rating;
  /** Ready again after waiting: its last Board move was out of Waiting, so a machine state from before it no longer describes the card. */
  released: boolean;
  /** The claim the sweeper released from the task, which left it unheld; absent or null when none ended the claim. */
  release?: ClaimRelease | null;
  /** When a held task's claim expires, epoch seconds; absent or null when the task is unheld, not working or before the first sweep pass. */
  claimExpiresAt?: number | null;
  /** The verdict on each Board column the task may move to, by state id; a column absent here has no transition. */
  moves: Record<string, Move>;
  /** When the task entered its column, epoch seconds; 0 when the server gave no time. */
  entered: number;
  /** When the task was created, epoch seconds; null when the board does not say. */
  created: number | null;
  /** Since when the task has been workable, epoch seconds; null when a dependency or its Start Criteria hold it. */
  workableSince: number | null;
  /** Every lifecycle machine the task is in: its state there, when it last moved, the machine's third-party source and its trail. */
  machines: { machine: string; state: string; at: number; source?: string | null; model?: string; steps?: number; trail: TrailStep[] }[];
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

/** Whether a task answers every word of the bar: a plain word is a substring of its id, title, a label or its holder's nickname, a `label:` word of a label alone. */
const matches = (t: KanbanTask, query: string) =>
  words(query).every((w) => {
    if (!w.startsWith(LABEL)) return [t.id, t.title, ...t.labels, sessionNickname(t.assignee) ?? ""].some((f) => f.toLowerCase().includes(w));
    const name = w.slice(LABEL.length);
    return t.labels.some((l) => l.toLowerCase().includes(name));
  });

const options = (tasks: KanbanTask[], columns: string[], of: (t: KanbanTask) => string, order: (a: Option, b: Option) => number): Option[] => {
  const counts = new Map<string, number>();
  for (const t of tasks.filter((x) => columns.includes(x.lane))) counts.set(of(t), (counts.get(of(t)) ?? 0) + 1);
  return [...counts].map(([value, count]) => ({ value, count })).sort(order);
};
/** Busiest first, the unassigned after the named. */
export const assigneeOptions = (tasks: KanbanTask[], columns: string[]) =>
  options(tasks, columns, (t) => t.assignee, (a, b) => Number(a.value === "") - Number(b.value === "") || b.count - a.count || a.value.localeCompare(b.value));
/** Newest first, as the buckets run, with No milestone last. */
export const milestoneOptions = (tasks: KanbanTask[], columns: string[]) => options(tasks, columns, (t) => t.milestone, (a, b) => milestoneNumber(b.value) - milestoneNumber(a.value));

/** One open milestone of the navigator's outline: how many of its tasks are done. */
export interface Outline {
  milestone: string;
  done: number;
  total: number;
}
/**
 * The milestones with a task not Done, by milestone number; tasks with no milestone have no row. A completed task has left the Board for
 * `settled`, so it is counted in `completed`, each milestone's count of them, done, or finishing a task would shrink its milestone's total
 * instead of raising its done count.
 */
export function milestoneOutline(tasks: KanbanTask[], roles: Roles, completed: Record<string, number> = {}): Outline[] {
  const counts = new Map<string, Outline>();
  const count = (milestone: string, done: boolean, n = 1) => {
    const row = counts.get(milestone) ?? { milestone, done: 0, total: 0 };
    row.total += n;
    if (done) row.done += n;
    counts.set(milestone, row);
  };
  for (const t of tasks) if (t.milestone) count(t.milestone, t.lane === roles.done);
  for (const [milestone, n] of Object.entries(completed)) if (milestone && n > 0) count(milestone, true, n);
  return [...counts.values()].filter((r) => r.done < r.total).sort((a, b) => milestoneNumber(a.milestone) - milestoneNumber(b.milestone));
}

/** The labels containing the word being typed (the last word of the bar, after a `label:` prefix), most used first. */
export function labelSuggestions(tasks: KanbanTask[], query: string, columns: string[]): { label: string; count: number }[] {
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
  /** The lifecycle role the column's State plays; absent on a board with no lifecycle roles. */
  role?: string;
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

/** A task in the working lane that no session holds, whatever released it. */
export const unheld = (t: KanbanTask, roles: Roles) => t.lane === roles.working && t.assignee === "";

/** The working lane's unheld tasks that the bar, profile and milestone filters and the hidden folds leave on the board. */
export const unheldShown = (tasks: KanbanTask[], roles: Roles, prefs: Prefs) =>
  tasks.filter((t) => unheld(t, roles) && !prefs.hiddenTasks.has(t.id) && !prefs.hiddenMilestones.has(t.milestone) && filtered(t, prefs));

/** A held claim this close to its expiry draws its minutes left, in seconds. */
const NEAR = 600;

/** What the footer chip says of a working card's claim: the session the sweeper expired and since when, or a held session's minutes left. */
export type ClaimChip = { kind: "expired"; session: string; age: string } | { kind: "near"; session: string; minutes: number };

/** The claim state a working card's footer chip adds to its assignee; null draws the chip as it is for any other card. */
export function claimChip(t: KanbanTask, roles: Roles, now: number): ClaimChip | null {
  if (t.lane !== roles.working) return null;
  if (unheld(t, roles)) return t.release ? { kind: "expired", session: t.release.session, age: ago(now - t.release.at) } : null;
  const left = t.claimExpiresAt == null ? Infinity : t.claimExpiresAt - now;
  return left < NEAR ? { kind: "near", session: t.assignee, minutes: Math.max(0, Math.ceil(left / 60)) } : null;
}

const byId = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

/** Whether the lane's tasks fold into stacks: the Waiting and Done lanes. */
export const stacked = (roles: Roles, lane: string) => lane === roles.waiting || lane === roles.done;

/**
 * A bucket's tasks of one lane as stacks. A Waiting task folds under its first blocker: of its Waiting dependencies in the bucket, the one
 * that unblocks first (lowest chain depth, then id). A Done task folds the other way, under the Done task that depends on it, so the chain's
 * last finished sits on top. A dependency in another milestone, or in another lane, does not stack.
 */
export function stacksOf(tasks: KanbanTask[], roles: Roles, lane = roles.waiting): Stack[] {
  const finished = !!lane && lane === roles.done;
  const here = new Map(tasks.map((t) => [t.id, t]));
  const links = new Map(tasks.map((t) => [t.id, [] as string[]]));
  for (const t of tasks) {
    for (const d of t.dependencies) {
      if (d === t.id || !here.has(d)) continue;
      if (finished) links.get(d)!.push(t.id);
      else links.get(t.id)!.push(d);
    }
  }
  if (finished) for (const l of links.values()) l.sort(byId);
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
export function crossOf(visible: KanbanTask[], roles: Roles): Map<string, KanbanTask[]> {
  const waiting = new Map(visible.filter((t) => t.lane === roles.waiting).map((t) => [t.id, t]));
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

export function layout(tasks: KanbanTask[], names: Record<string, string>, roles: Roles, prefs: Prefs, now: number): Layout {
  const lanes = columnsOf(names, roles);
  const drawn = recent(tasks, now, roles).filter((t) => lanes.includes(t.lane));
  const visible = drawn.filter(
(t) => !prefs.hiddenTasks.has(t.id) && !prefs.hiddenMilestones.has(t.milestone) && filtered(t, prefs));
  const columns = lanes.map((id): Column => {
    const here = visible.filter((t) => t.lane === id).sort((a, b) => b.entered - a.entered || b.id.localeCompare(a.id, undefined, { numeric: true }));
    const keys = [...new Set(here.map((t) => t.milestone))].sort((a, b) => milestoneNumber(b) - milestoneNumber(a));
    const buckets = keys.map((milestone): Bucket => {
      const inBucket = here.filter((t) => t.milestone === milestone);
      return { milestone, tasks: inBucket, stacks: stacked(roles, id) ? stacksOf(inBucket, roles, id) : [], folded: prefs.folded.has(milestone) };
    });
    return { id, name: names[id] ?? id, role: roleOf(roles, id), count: here.length, buckets };
  });
  const done = columns.find((c) => c.id === roles.done)?.count ?? 0;
  return {
    columns, cross: crossOf(visible, roles), open: visible.length - done, done, shown: visible.length, total: drawn.length,
    hidden: prefs.hiddenMilestones.size + prefs.hiddenTasks.size,
  };
}

/** Why task `id` has no card in view: Done before today, hidden, its milestone hidden, filtered out or folded away; null when its card is drawn. */
export function whyHidden(tasks: KanbanTask[], names: Record<string, string>, roles: Roles, prefs: Prefs, id: string, now: number): string | null {
  const t = tasks.find((x) => x.id === id);
  if (!t || !columnsOf(names, roles).includes(t.lane)) return "not on the board";
  if (!recent([t], now, roles).length) return "Done before today";
  if (prefs.hiddenTasks.has(id)) return "hidden";
  if (prefs.hiddenMilestones.has(t.milestone)) return "its milestone is hidden";
  if (!filtered(t, prefs)) return "filtered out";
  return prefs.folded.has(t.milestone) ? "in a folded milestone" : null;
}

/** Each pull request a task cites, as GitHub was last read for it; one not read yet is drawn unread (`stale`) rather than left off. */
const cited = (urls: string[], read: Pull[]): Pull[] => {
  const unread = urls.filter((url) => !read.some((p) => p.url === url));
  return [...read, ...unread.map((url) => ({ number: Number(/(\d+)\/?$/.exec(url)?.[1] ?? 0), repo: /github\.com\/([^/]+\/[^/]+)\/pull\//.exec(url)?.[1] ?? "", url, checks: "none" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: true }))];
};

/** The Board's tasks as cards: its own fields, the pull requests the server read for it and the machine that last placed it. */
export function kanbanTasks(sky: Sky): KanbanTask[] {
  const { roles } = sky;
  const open = new Set(sky.board.agents.filter((a) => a.state !== roles.done).map((a) => a.id));
  // every machine's sessions by task, read in one pass over the machines and kept in their order
  const sessions = new Map<string, KanbanTask["machines"]>();
  for (const f of Object.values(sky.flows)) {
    if (f.name === "board") continue;
    for (const m of f.agents) {
      if (!m.task) continue;
      const row = { machine: f.name, state: m.state, at: m.active ?? 0, source: f.machine.source, model: m.model, steps: m.steps ?? 0, trail: m.trail ?? [] };
      sessions.set(m.task, [...(sessions.get(m.task) ?? []), row]);
    }
  }
  return sky.board.agents.map((a) => {
    const latest = sky.latest[a.id], dependencies = a.dependencies ?? [];
    return {
      id: a.id, title: a.title, lane: a.state, milestone: a.milestone ?? "", labels: a.labels ?? [], assignee: a.assignee ?? "", dependencies,
      openDeps: dependencies.filter((d) => open.has(d)).length, prs: cited(a.prs ?? [], sky.pulls[a.id] ?? []), runs: a.runs ?? [], description: a.description ?? "",
      live: latest ? { machine: latest.flow, state: latest.state, at: latest.at, source: sky.flows[latest.flow]?.machine.source } : null,
      released: a.state === roles.ready && a.previous === roles.waiting, release: a.released ?? null, claimExpiresAt: a.claim_expires_at ?? null, moves: a.moves ?? (a.move_set ? sky.moveSets[a.move_set] : undefined) ?? {}, entered: a.entered ?? 0, created: a.created ?? null, workableSince: a.workable_since ?? null,
      machines: sessions.get(a.id) ?? [],
      rating: sky.ratings?.[a.id],
    };
  });
}

/** The dependency edges between open tasks: each task's open dependencies, and each task's Waiting dependents. */
function edges(tasks: KanbanTask[], roles: Roles) {
  const open = new Set(tasks.filter((t) => t.lane !== roles.done).map((t) => t.id));
  const waitsOn = new Map<string, string[]>(), heldBy = new Map<string, string[]>();
  for (const t of tasks) {
    const deps = t.dependencies.filter((d) => open.has(d));
    if (t.lane === roles.done || !deps.length) continue;
    waitsOn.set(t.id, deps);
    if (t.lane === roles.waiting) for (const d of deps) heldBy.set(d, [...(heldBy.get(d) ?? []), t.id]);
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
export function chainOf(tasks: KanbanTask[], id: string, roles: Roles): { holds: Set<string>; waitsOn: Set<string> } {
  const e = edges(tasks, roles);
  return { holds: reach(id, e.heldBy), waitsOn: reach(id, e.waitsOn) };
}

/** How many Waiting tasks each task holds: those that depend on it while it is not Done, directly or through other Waiting tasks, each counted once. */
export function holdCounts(tasks: KanbanTask[], roles: Roles): Map<string, number> {
  const { heldBy } = edges(tasks, roles);
  return new Map([...heldBy.keys()].map((id) => [id, reach(id, heldBy).size]));
}

/** The tasks at the bottom of the Waiting chains, most held first: each holds Waiting work and is not itself waiting on open work. */
export function holders(tasks: KanbanTask[], roles: Roles, counts = holdCounts(tasks, roles)): { task: KanbanTask; holds: number }[] {
  return tasks
    .filter((t) => (counts.get(t.id) ?? 0) > 0 && !(t.lane === roles.waiting && t.openDeps > 0))
    .map((task) => ({ task, holds: counts.get(task.id)! }))
    .sort((a, b) => b.holds - a.holds || a.task.id.localeCompare(b.task.id, undefined, { numeric: true }));
}
