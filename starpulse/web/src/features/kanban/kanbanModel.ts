// The Kanban view's model: the Board's open tasks laid out as columns of milestone buckets. Pure, so the view only draws it.
import { descend, type Sky } from "../../render/sky";
import { skillOf } from "../../render/skills";
import type { TaskRecord } from "./taskViewModel";
import type { Option } from "../../shared/ChoiceMenu";
import type { ClaimRelease, Frozen, MachineState, Move, Pull, Roles, TrailStep } from "../../api";
import { ago } from "../../shared/clock";
import { sessionNickname } from "./nickname";

/** The States the machine gives a lifecycle role, keyed by role: what stacking, the unheld chip, the Done cutoff and a lane's tone read. */
const lifecycleStates = ({ ready, waiting, working, review, verifying, attention, done }: Roles) => ({ ready, waiting, working, review, verifying, attention, done });

/** The role a State plays in the lifecycle columns, when it plays one. */
export const roleOf = (roles: Roles, state: string): string | undefined => Object.entries(lifecycleStates(roles)).find(([, s]) => s === state)?.[0];

/** The lanes drawn as columns: the snapshot's `roles.lanes` as the server sends them, which it derives from the machine file (a native board's statuses when it has none). None before the snapshot arrives. */
export const columnsOf = (roles: Roles): string[] => roles.lanes ?? [];

/** How many of `tasks` the Kanban draws: the cards in its columns, none in the Done or Proposed lane. */
export const boardCount = (tasks: KanbanTask[], roles: Roles): number => {
  const lanes = columnsOf(roles);
  return tasks.filter((t) => lanes.includes(t.lane)).length;
};

const ACTOR_FAULT = /^## Needs attention[ \t]*\n\s*(Task actor fault:[^\n]*)/m;

/** The reason the task actor parked the task with, empty when its Needs attention section does not open with a fault: the card draws the actor-error chip for a non-empty one. */
export const actorFault = (description: string): string => ACTOR_FAULT.exec(description)?.[1].trim() ?? "";

export interface KanbanTask {
  id: string;
  title: string;
  lane: string;
  /** The milestone key the snapshot carries (`m-76`); empty when the task has none. */
  milestone: string;
  labels: string[];
  /** The session that holds the task; empty when unheld. */
  assignee: string;
  /** The agent profile the task is routed to (`@agent-standard-high`); empty when it has none. */
  profile?: string;
  dependencies: string[];
  /** Dependencies still on the Board and not Done. */
  openDeps: number;
  prs: Pull[];
  /** The scheduler runs whose run id names the task, each linked to the run's page. */
  runs?: { url: string; status: string; startedAt: string }[];
  description: string;
  /** The task's acceptance criteria and Definition of Done as the snapshot carries them; absent when the snapshot slims them off. */
  acceptanceCriteria?: { n: number; text: string; checked: boolean }[];
  definitionOfDone?: { n: number; text: string; checked: boolean }[];
  /** The lifecycle machine that last placed the task, the state it left it in and when (epoch seconds). */
  live: { machine: string; state: string; at: number; source?: string | null; skill?: string } | null;
  /** The phase machine the task is in and its step, when it is in one: see `climb`. */
  phase?: PhaseAt | null;
  /** The first `readable` guard rule the description breaks, empty when it reads well: the card draws the legacy-format badge for a non-empty one, the dialog none. */
  readable?: string;
  /** Ready again after waiting: its last Board move was out of Waiting, so a machine state from before it no longer describes the card. */
  released: boolean;
  /** The freeze the task actor holds the task in, who asked and why; absent or null when the task runs free. */
  frozen?: Frozen | null;
  /** The claim the sweeper released from the task, which left it unheld; absent or null when none ended the claim. */
  release?: ClaimRelease | null;
  /** What the holder session is doing, from the snapshot; absent unless the task is held and working. */
  sessionActivity?: { state: "working" | "idle" | "unknown"; last_turn_at?: string | null } | null;
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
  profile: record.profile,
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
const numbered = (items: { text: string; checked: boolean }[]) => items.map((item, i) => ({ n: i + 1, text: item.text, checked: item.checked }));

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
 * Waiting tasks of one bucket folded along their dependency chains. A stack's top waits on nothing else Waiting in the bucket and the rest
 * sit under it in unblock order.
 */
export interface Stack {
  top: KanbanTask;
  /** The top first, then the rest by chain depth, then id. */
  members: KanbanTask[];
  /** Each member's neighbours toward the top: the Waiting dependencies it waits on, in the bucket. */
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

/** What the footer chip says of a working card whose claim ended: its struck session and how long the task has sat idle. */
export type ClaimChip = { session: string; age: string };

/** What a held working card says of its session: how long it has sat idle since its last turn, `unknown` when no running session holds the task, nothing while it works. */
export type SessionChip = { kind: "idle"; age: string } | { kind: "unknown" };

export const sessionChip = (t: KanbanTask, now: number): SessionChip | null => {
  const a = t.sessionActivity;
  if (a?.state === "unknown") return { kind: "unknown" };
  return a?.state === "idle" && a.last_turn_at ? { kind: "idle", age: idleAge(now - Date.parse(a.last_turn_at) / 1000) } : null;
};

/** How long a claim has sat idle, counting up by the minute: "<1m", "1m", "2m". */
export const idleAge = (seconds: number) => (seconds < 60 ? "<1m" : ago(seconds));

/** The idle claim a working card's footer chip adds to its assignee; null draws the chip as it is for any other card. */
export function claimChip(t: KanbanTask, roles: Roles, now: number): ClaimChip | null {
  const r = t.release;
  if (t.lane !== roles.working || !unheld(t, roles) || !r) return null;
  // a swept claim went idle when its TTL ran out, before the sweep that released it; an idle reap has no TTL to run out
  return { session: r.session, age: idleAge(now - (r.ttl ? r.last_renewal + r.ttl : r.at)) };
}

const byId = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

/** Whether the lane's tasks fold into stacks: the Waiting lane. */
export const stacked = (roles: Roles, lane: string) => lane === roles.waiting;

/**
 * A bucket's Waiting tasks as stacks. A Waiting task folds under its first blocker: of its Waiting dependencies in the bucket, the one
 * that unblocks first (lowest chain depth, then id). A dependency in another milestone, or in another lane, does not stack.
 */
export function stacksOf(tasks: KanbanTask[]): Stack[] {
  const here = new Map(tasks.map((t) => [t.id, t]));
  const links = new Map(tasks.map((t) => [t.id, [] as string[]]));
  for (const t of tasks) {
    for (const d of t.dependencies) {
      if (d !== t.id && here.has(d)) links.get(t.id)!.push(d);
    }
  }
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

export function layout(tasks: KanbanTask[], names: Record<string, string>, roles: Roles, prefs: Prefs): Layout {
  const lanes = columnsOf(roles);
  const drawn = tasks.filter((t) => lanes.includes(t.lane));
  const visible = drawn.filter(
(t) => !prefs.hiddenTasks.has(t.id) && !prefs.hiddenMilestones.has(t.milestone) && filtered(t, prefs));
  const columns = lanes.map((id): Column => {
    const here = visible.filter((t) => t.lane === id).sort((a, b) => b.entered - a.entered || b.id.localeCompare(a.id, undefined, { numeric: true }));
    const keys = [...new Set(here.map((t) => t.milestone))].sort((a, b) => milestoneNumber(b) - milestoneNumber(a));
    const buckets = keys.map((milestone): Bucket => {
      const inBucket = here.filter((t) => t.milestone === milestone);
      return { milestone, tasks: inBucket, stacks: stacked(roles, id) ? stacksOf(inBucket) : [], folded: prefs.folded.has(milestone) };
    });
    return { id, name: names[id] ?? id, role: roleOf(roles, id), count: here.length, buckets };
  });
  return {
    columns, cross: crossOf(visible, roles), shown: visible.length, total: drawn.length,
    hidden: prefs.hiddenMilestones.size + prefs.hiddenTasks.size,
  };
}

/** Why task `id` has no card in view: Done, hidden, its milestone hidden, filtered out or folded away; null when its card is drawn. */
export function whyHidden(tasks: KanbanTask[], roles: Roles, prefs: Prefs, id: string): string | null {
  const t = tasks.find((x) => x.id === id);
  if (t && t.lane === roles.done) return "Done";
  if (!t || !columnsOf(roles).includes(t.lane)) return "not on the board";
  if (prefs.hiddenTasks.has(id)) return "hidden";
  if (prefs.hiddenMilestones.has(t.milestone)) return "its milestone is hidden";
  if (!filtered(t, prefs)) return "filtered out";
  return prefs.folded.has(t.milestone) ? "in a folded milestone" : null;
}

/** What the dialog draws of a cited pull request: its state, check result and unread reviews, or why it has not been read. */
export type PrReadState =
  | { read: true; state: "open" | "merged" | "closed"; checks: Pull["checks"]; unreviewed: number }
  | { read: false; label: "not read yet"; reason: string };

/** An unread citation (`cited` marks it `stale`) is not read yet, never a failed read or no checks: the PR store reads every repository a task cites, so none waits on a grant. */
const CI_TONES: Record<string, string> = { merged: "merged", closed: "closed", failing: "fail", conflicting: "fail", passing: "pass", queued: "pending" };
/** The checks colour a `ci` state draws in: merged, closed, failing, passing and queued keep theirs, and every other phase is blue. */
export const ciTone = (state: string) => CI_TONES[state] ?? "phase";

export const prReadState = (p: Pull): PrReadState =>
  p.stale
    ? { read: false, label: "not read yet", reason: "no read since it was cited" }
    : { read: true, state: p.merged ? "merged" : p.closed ? "closed" : "open", checks: p.checks, unreviewed: p.threads };

const CI_OF_CHECKS = { failing: "failing", pending: "running", pass: "passing" } as const;
/** The `ci` state a card shows: while the machine is running, passing or failing, the worst check status of the task's open read pull requests, the one status the Review gate reads; else the machine's own state. */
const ciState = (state: string, prs: Pull[]): string => {
  if (!(state === "running" || state === "passing" || state === "failing")) return state;
  const worst = (["failing", "pending", "pass"] as const).find((c) => prs.some((p) => !p.stale && !p.merged && !p.closed && p.checks === c));
  return worst ? CI_OF_CHECKS[worst] : state;
};

/** Each pull request a task cites, as GitHub was last read for it; one not read yet is drawn unread (`stale`) rather than left off. */
const cited = (urls: string[], read: Pull[]): Pull[] => {
  const unread = urls.filter((url) => !read.some((p) => p.url === url));
  return [...read, ...unread.map((url) => ({ number: Number(/(\d+)\/?$/.exec(url)?.[1] ?? 0), repo: /github\.com\/([^/]+\/[^/]+)\/pull\//.exec(url)?.[1] ?? "", url, checks: "none" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: true }))];
};

const pullUrls = (record: TaskRecord) => (record.references ?? []).filter((url) => /github\.com\/[^/]+\/[^/]+\/pull\/\d+\/?$/.test(url));

/** A Done task's card with the pull requests its record cites beside those read: the snapshot's Done entry carries none, so the PR that closed it comes with the record. */
export const withRecordPulls = (task: KanbanTask, record: TaskRecord, roles: Roles): KanbanTask =>
  task.lane === roles.done ? { ...task, prs: cited(pullUrls(record), task.prs) } : task;

/** A Done task the snapshot leaves out, as its modal and a dependency rail draw it from its record; null for a record that is not Done, which only an archived task has off the board. */
export function offBoardTask(id: string, record: TaskRecord, roles: Roles): KanbanTask | null {
  const lane = (record.status ?? "").toLowerCase().replace(/ /g, "_");
  if (lane !== roles.done && lane !== "completed") return null;
  const prs = cited(pullUrls(record), []);
  return applyTaskRecord({ id, title: "", lane: roles.done ?? lane, milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs, description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [] }, record);
}

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
    const latest = sky.latest[a.id], dependencies = a.dependencies ?? [], prs = cited(a.prs ?? [], sky.pulls[a.id] ?? []);
    return {
      id: a.id, title: a.title, lane: a.state, milestone: a.milestone ?? "", labels: a.labels ?? [], assignee: a.assignee ?? "", profile: a.profile ?? "", dependencies,
      openDeps: dependencies.filter((d) => open.has(d)).length, prs, runs: a.runs ?? [], description: a.description ?? "",
      live: latest ? { machine: latest.flow, state: latest.flow === "ci" ? ciState(latest.state, prs) : latest.state, at: latest.at, source: sky.flows[latest.flow]?.machine.source, skill: skillOf(sky.flows, latest.flow) } : null,
      released: a.state === roles.ready && a.previous === roles.waiting, release: a.released ?? null, frozen: a.frozen ?? null, sessionActivity: a.session_activity ?? null, moves: a.moves ?? (a.move_set ? sky.moveSets[a.move_set] : undefined) ?? {}, entered: a.entered ?? 0, created: a.created ?? null, workableSince: a.workable_since ?? null,
      machines: sessions.get(a.id) ?? [],
      phase: climb(sky, a.id),
      ...(a.readable ? { readable: a.readable } : {}),
      ...(a.criteria ? { acceptanceCriteria: numbered(a.criteria) } : {}),
      ...(a.definition_of_done ? { definitionOfDone: numbered(a.definition_of_done) } : {}),
    };
  });
}

/** Where a task stands in its phase machines: the machines from its phase down to the one it is in, outermost first, that machine's step and when it took it, that machine's states in order, and the skill the phase runs. */
export interface PhaseAt { chain: string[]; state: string; at: number; track: MachineState[]; skill?: string }

/** The phase machine `id` is in and its step: from the step it holds in the In Progress machine (the Board's first sub-flow) down the submachine links declared on that step, each machine's newest session and never a machine already on the way down, so a newer row of a machine its step does not declare never stands in for the phase; a task whose row there names no phase with a row takes whichever phase holds its newest row; null for a task in no phase machine, the In Progress machine itself included. */
export function climb(sky: Sky, id: string): PhaseAt | null {
  const found = descend(sky.flows, id, sky.board.machine.submachines?.[0]?.machine ?? ""), flow = found && sky.flows[found.machine];
  return found && flow && found.chain.length ? { chain: found.chain, state: found.row.state, at: found.row.active ?? 0, track: flow.machine.states, skill: skillOf(sky.flows, found.chain[0]) } : null;
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

/** Where each card sits in the hovered card's chain: the hovered card itself ("alone" when its chain is empty), a Waiting task it holds, an open task it waits on. */
export function chainRole(tasks: KanbanTask[], hovered: string, roles: Roles): (id: string) => "self" | "alone" | "holds" | "waits" | undefined {
  const c = chainOf(tasks, hovered, roles);
  const self = c.holds.size || c.waitsOn.size ? "self" : "alone";
  return (id) => (id === hovered ? self : c.holds.has(id) ? "holds" : c.waitsOn.has(id) ? "waits" : undefined);
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
