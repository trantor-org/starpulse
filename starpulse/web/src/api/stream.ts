// The board the page draws: one read of its view's queries, then the subscriptions that follow them.

import type { Cue, Dag, Delta, Domain, Jobs, LedgerRow, Machine, MergeStrip, Pool, Pull, RawTask, Roles, Settled, Snapshot, TaskRun } from ".";
import { apiFetch } from "./apiFetch";
import { openHealth, type Health, type Watch } from "./health";
import { followJobs, readJobs } from "./jobs";
import { openLedger, type LedgerMarks } from "./ledgerStream";
import { LOST_MS, retryWait } from "./retry";
import { keep, same } from "./same";
import { follow, type Post } from "./subscribe";
import { deriveTies } from "./ties";

/** One event's rows with `changed` replacing the same keys or joining by time (newest first); every other row stays as it was. */
export function foldRows(rows: LedgerRow[], changed: LedgerRow[]): LedgerRow[] {
  const replaced = new Map(changed.map((row) => [row.key, row]));
  const held = new Set(rows.map((row) => row.key));
  const kept = rows.map((row) => replaced.get(row.key) ?? row);
  const added = changed.filter((row) => !held.has(row.key));
  return added.length ? [...kept, ...added].sort((x, y) => y.at - x.at) : kept;
}

/** What the connection is doing: up, down after the server announced a restart, down with no announcement, or down for LOST_MS. `stale` is the page still showing the Board it held when the connection dropped, until the new read is handed over. */
export type Link = "live" | "restarting" | "retrying" | "offline" | "stale";

export interface StreamHandlers {
  /** The sky as it stands: the read, then that read folded with every change after it, `kind` naming that change. */
  snapshot(sky: Snapshot, kind?: Delta["kind"]): void;
  /** Whether the connection is up. */
  live(on: boolean): void;
  /** What the connection is doing, each time that changes: `restarting` from the server's announcement, even while the connection is still open. */
  link?(state: Link): void;
  /** The server named a page build other than the one the page holds, once per such build, once that server has read its board. */
  build?(id: string): void;
  /** How many seconds the server's clock is ahead of the page's, from the server's time on each health event. */
  clock?(skew: number): void;
}

const TASK =
  "id title lane profile impact urgency tier source assignee labels milestone type dependencies workable createdAt movedAt description " +
  "prs { repo number state isDraft mergeable checks threads mergedAt mergeSha } lanePath { from } criteria { text checked } pauseReason readable " +
  "released { at session last_renewal ttl idle } sessionActivity { state last_turn_at } skill { name states current next { kind name } } phase substate";
const SETTLED = "id state at created title model milestone labels";
const MACHINE_TASK = "machine id title model task state steps active trail { state event at id }";
const MACHINE =
  "name source states { id name initial final role priority } transitions { source target event cite { skill quote } } " +
  "submachines { state machine exits parent when routes skill } launches writers next { kind name } dagActors mainLine tiers";
const READ =
  `query { tasks { position items { ${TASK} } settled { ${SETTLED} } milestoneDone { milestone done } archivedToday machineTasks { ${MACHINE_TASK} } } ` +
  `board { roles { initial final done working ready waiting review verifying attention startable lanes } machines { ${MACHINE} } } }`;
const TASK_CHANGES = `subscription ($from: Int!) { taskChanges(from: $from) { id machine task { ${TASK} } settled { ${SETTLED} } machineTask { ${MACHINE_TASK} } } }`;

interface GqlPull {
  repo: string;
  number: number;
  state: string;
  isDraft: boolean;
  mergeable: string;
  checks: Pull["checks"];
  threads: number;
  mergedAt: string | null;
  mergeSha: string | null;
}
type GqlTask = Pick<RawTask, "id" | "title" | "profile" | "impact" | "urgency" | "tier" | "source" | "assignee" | "labels" | "milestone" | "type" | "dependencies" | "workable" | "description" | "criteria" | "readable" | "released" | "skill"> & {
  lane: string;
  createdAt: number;
  movedAt: number;
  prs: GqlPull[];
  lanePath: { from: string | null }[];
  pauseReason: string;
  sessionActivity: RawTask["session_activity"];
  phase: string | null;
  substate: string | null;
};
type GqlSettled = Settled & { id: string };
type GqlMachineTask = Pick<RawTask, "id" | "title" | "model" | "task" | "state" | "steps" | "active" | "trail">;
interface GqlChange {
  id: string;
  machine: string;
  task: GqlTask | null;
  settled: GqlSettled | null;
  machineTask: GqlMachineTask | null;
}
interface Read {
  tasks: { position: number; items: GqlTask[]; settled: GqlSettled[]; milestoneDone: { milestone: string; done: number }[]; archivedToday: number; machineTasks: (GqlMachineTask & { machine: string })[] };
  board: { roles: Roles; machines: Machine[] & { name: string }[] };
}

const prUrl = (p: Pick<GqlPull, "repo" | "number">) => `https://github.com/${p.repo}/pull/${p.number}`;
const pullOf = (p: GqlPull): Pull => ({
  repo: p.repo, number: p.number, url: prUrl(p), checks: p.checks, threads: p.threads,
  merged: p.state === "MERGED", closed: p.state === "CLOSED", draft: p.isDraft, conflicting: p.mergeable === "CONFLICTING",
  merge_sha: p.mergeSha, merged_at: p.mergedAt, stale: false,
});

/** A task as the page's card holds it: the view's fields renamed to the card's, its `runs` the scheduler runs that name it. */
const taskOf = ({ lane, createdAt, movedAt, prs, lanePath, pauseReason, sessionActivity, ...t }: GqlTask, runs: TaskRun[]): RawTask => ({
  ...t, state: lane, model: t.profile ?? "", created: createdAt, entered: movedAt, workable_since: t.workable ? movedAt : null,
  previous: lanePath.at(-1)?.from ?? null, prs: prs.map(prUrl), pause_reason: pauseReason, session_activity: sessionActivity, runs,
});
const settledOf = ({ id: _id, ...s }: GqlSettled): Settled => s;

/** The scheduler runs that name a task, newest first, by task id. */
function runsByTask(dags: Dag[]): Map<string, TaskRun[]> {
  const by = new Map<string, TaskRun[]>();
  const seen = new Set<string>();
  for (const dag of dags)
    for (const run of [...(dag.active ?? []), ...(dag.failed ?? []), ...(dag.closed ?? [])]) {
      if (!run.task || seen.has(run.runId)) continue;
      seen.add(run.runId);
      by.set(run.task, [...(by.get(run.task) ?? []), { startedAt: run.startedAt, status: run.status, url: run.url ?? "" }]);
    }
  for (const runs of by.values()) runs.sort((a, b) => b.startedAt.localeCompare(a.startedAt));
  return by;
}

/** The milestone a settled task counts toward in `milestone_done`: the one it completed in (settled in the `final` State), if any. */
const completedIn = (final: string | null | undefined, entry: Settled | null | undefined) => (final && entry?.state === final && entry.milestone ? entry.milestone : null);

/** `done` with a task's settling `was` taken back and `now` counted; `done` itself when neither counts. */
function recount(done: Record<string, number>, final: string | null | undefined, was: Settled | undefined, now: Settled | undefined): Record<string, number> {
  const [from, to] = [completedIn(final, was), completedIn(final, now)];
  if (from === to) return done;
  const next = { ...done };
  if (from) next[from] = (next[from] ?? 0) - 1;
  if (to) next[to] = (next[to] ?? 0) + 1;
  return next;
}

/** Everything one connection's reads and changes add up to. */
interface Held {
  cards: Map<string, RawTask>;
  others: Map<string, Map<string, RawTask>>;
  pulls: Record<string, Pull[]>;
  settled: Record<string, Settled>;
  done: Record<string, number>;
  archived: number;
  roles: Roles;
  machines: Machine[];
  dags: Dag[];
  domains: Domain[];
  cues: Cue[];
  pools: Pool[];
  error: string | null;
  runs: Map<string, TaskRun[]>;
  strip: MergeStrip | null;
  pins: LedgerRow[];
}

const hold = (read: Read, jobs: Jobs): Held => {
  const runs = runsByTask(jobs.items);
  const held: Held = {
    cards: new Map(), others: new Map(), pulls: {}, settled: Object.fromEntries(read.tasks.settled.map((s) => [s.id, settledOf(s)])),
    done: Object.fromEntries(read.tasks.milestoneDone.map((m) => [m.milestone, m.done])), archived: read.tasks.archivedToday,
    roles: read.board.roles, machines: read.board.machines, dags: jobs.items, domains: jobs.domains, cues: jobs.cues, pools: jobs.pools, error: jobs.error,
    runs, strip: null, pins: [],
  };
  for (const t of read.tasks.items) upsertCard(held, t);
  for (const { machine, ...t } of read.tasks.machineTasks) upsertOther(held, machine, t);
  return held;
};

function upsertCard(held: Held, t: GqlTask): boolean {
  const before = held.cards.get(t.id);
  const card = keep<RawTask | undefined>(before, taskOf(t, held.runs.get(t.id) ?? []))!;
  const pulls = keep(held.pulls[t.id], t.prs.map(pullOf));
  if (pulls !== held.pulls[t.id]) held.pulls = pulls.length ? { ...held.pulls, [t.id]: pulls } : Object.fromEntries(Object.entries(held.pulls).filter(([id]) => id !== t.id));
  if (card === before) return false;
  held.cards.set(t.id, card);
  return true;
}

function upsertOther(held: Held, machine: string, t: GqlMachineTask): boolean {
  const tasks = held.others.get(machine) ?? new Map<string, RawTask>();
  const before = tasks.get(t.id);
  const next = keep<RawTask | undefined>(before, t as RawTask)!;
  held.others.set(machine, tasks);
  if (next === before) return false;
  tasks.set(t.id, next);
  return true;
}

/** `held` with one task change folded in; whether anything differs. */
function foldChange(held: Held, c: GqlChange): boolean {
  let changed = false;
  const was = held.cards.has(c.id) || c.id in held.settled;
  if (c.task) changed = upsertCard(held, c.task) || changed;
  if (c.machineTask) changed = upsertOther(held, c.machine, c.machineTask) || changed;
  if (c.machine !== "board") return (!c.machineTask && held.others.get(c.machine)?.delete(c.id)) || changed;
  if (!c.task && held.cards.delete(c.id)) {
    held.pulls = Object.fromEntries(Object.entries(held.pulls).filter(([id]) => id !== c.id));
    changed = true;
  }
  const [before, after] = [held.settled[c.id], c.settled ? settledOf(c.settled) : undefined];
  if (!same(before, after)) {
    held.done = recount(held.done, held.roles.final, before, after);
    held.settled = after ? { ...held.settled, [c.id]: after } : Object.fromEntries(Object.entries(held.settled).filter(([id]) => id !== c.id));
    changed = true;
  }
  if (!c.task && !c.settled && was) {
    held.archived += 1; // a task the board no longer holds and no settled entry shows was archived
    changed = true;
  }
  return changed;
}

/** `held` with the jobs list and what rides beside it folded in; whether anything differs. */
function foldJobs(held: Held, list: Dag[], error: string | null, beside: { domains: Domain[]; cues: Cue[]; pools: Pool[] }): boolean {
  const [dags, domains, cues, pools] = [keep(held.dags, list, (d) => d.name), keep(held.domains, beside.domains ?? [], (d) => d.name), keep(held.cues, beside.cues ?? []), keep(held.pools, beside.pools ?? [], (p) => p.name)];
  if (dags === held.dags && domains === held.domains && cues === held.cues && pools === held.pools && error === held.error) return false;
  Object.assign(held, { dags, domains, cues, pools, error });
  held.runs = runsByTask(dags);
  for (const [id, card] of held.cards) {
    const runs = held.runs.get(id) ?? [];
    if (!same(card.runs ?? [], runs)) held.cards.set(id, { ...card, runs });
  }
  return true;
}

function foldMarks(held: Held, marks: LedgerMarks): boolean {
  const [strip, pins] = [keep(held.strip, marks.mergeStrip), keep(held.pins, marks.mergePins, (r) => r.key)];
  if (strip === held.strip && pins === held.pins) return false;
  Object.assign(held, { strip, pins });
  return true;
}

/** The snapshot the page draws from what is held, at `now`. */
function skyOf(held: Held, reading: boolean, now: number): Snapshot {
  const flows = held.machines.map((machine) => ({
    name: machine.name as string,
    machine,
    agents: [...(machine.name === "board" ? held.cards : (held.others.get(machine.name as string) ?? new Map<string, RawTask>())).values()],
    names: [] as string[],
  }));
  const ties = deriveTies(flows, now);
  return {
    flows: flows.map((f) => (f.name === "board" ? f : { ...f, ...ties[f.name] })),
    graphs: [...flows.map((f) => f.name), "runs"],
    roles: held.roles,
    dags: held.dags, domains: held.domains, cues: held.cues, pools: held.pools, error: held.error,
    settled: held.settled, milestone_done: held.done, archived_today: held.archived, pulls: held.pulls,
    mergeStrip: held.strip, mergePins: held.pins, reading, now,
  };
}

/**
 * One read of the board (`tasks` and `board` over POST /graphql, the jobs over POST /api/jobs), then the subscriptions that follow it
 * (`taskChanges` and `jobChanges` from the positions the reads answered, the merge Ledger's marks) and one health subscription (`watch`)
 * that says whether the server announced a restart, whether it is still reading its board, which page build it serves and what time it
 * is. Any of them ending ends the connection: the page reads again at once, then after 250 ms, 500 ms and so on up to RETRY_CAP_MS, and
 * a position the server no longer holds (a 410) is read again at once. A page holds what it drew through the drop, marked `stale`.
 */
export function openStream(handlers: StreamHandlers, post: Post = apiFetch, watch: Watch = (on) => openHealth(on, post)): { close(): void } {
  const stop = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let lost: ReturnType<typeof setTimeout> | undefined;
  let held: Held | null = null;
  let skew = 0;
  /** What is open now: closed when the connection ends, whichever of its streams ended it. */
  let open: { close(): void } | null = null;
  /** A restarted server's partial Board is not handed over once the page has drawn one: the page keeps its own until the server has read its board. */
  let shown = false;
  /** Set while the Board the page shows predates the connection: the one held through a drop, until the server's whole one is handed over. */
  let old = false;
  /** Set from a connect until its health says the server's board component is ready: the Board it sends may be partial. */
  let reading = true;
  /** Set when `hand` held a snapshot back for `reading`, or handed one flagged `reading`, so it is handed over again once the server has read its board. */
  let redo = false;

  const hand = (kind?: Delta["kind"]) => {
    if (!held) return;
    if (shown && reading) {
      redo = true;
      return;
    }
    redo = reading;
    shown = true;
    handlers.snapshot(skyOf(held, reading, Date.now() / 1000 + skew), kind);
    if (!old || reading) return;
    old = false;
    if (showing === "stale") show("live");
  };

  let showing: Link | null = null;
  const show = (state: Link) => {
    if (state === showing) return;
    showing = state;
    handlers.link?.(state);
  };
  let attempts = 0;
  let announced = false;
  let connected = false;
  const goesLost = () => void (lost ??= setTimeout(() => show("offline"), LOST_MS));
  const up = () => {
    clearTimeout(lost);
    lost = undefined;
    attempts = 0;
    announced = false;
    show(old ? "stale" : "live");
    handlers.live(true);
  };
  const drop = () => {
    old ||= shown;
    handlers.live(false);
    if (showing !== "offline") show(announced ? "restarting" : "retrying");
    goesLost();
    clearTimeout(timer);
    if (!stop.signal.aborted) timer = setTimeout(connect, retryWait(attempts++));
  };

  /** The page build the page's own first connection named, which the page was loaded from. */
  let own: string | null = null;
  let told: string | null = null;
  /** A build the page has not reported yet because its server was still reading its board: a page reloaded onto it then would draw the partial Board. */
  let pending: string | null = null;
  const tell = () => {
    if (pending === null || reading) return;
    handlers.build?.((told = pending));
    pending = null;
  };

  /** What the server's health says: a restart it announced, whether its board is read, the build it serves and its clock. */
  const onHealth = (h: Health) => {
    if (!connected) {
      connected = true;
      up();
    }
    if (h.restarting && !announced) {
      announced = true;
      show("restarting");
      goesLost();
    }
    reading = h.components.some((c) => c.name === "board" && !c.ready);
    if (h.build !== null) {
      if (own === null) own = h.build;
      else if (h.build !== own && h.build !== told) pending = h.build;
    }
    skew = h.at - Date.now() / 1000;
    handlers.clock?.(skew);
    if (reading) return;
    if (redo || old) hand(); // a partial Board stays withheld: it is handed over once the server has read its board
    tell();
  };

  async function connect() {
    const streams: { close(): void }[] = [];
    let over = false;
    const end = (why: "closed" | "reread" = "closed") => {
      if (over) return;
      over = true;
      streams.forEach((s) => s.close());
      if (why === "reread") void connect();
      else drop();
    };
    open = { close: () => ((over = true), streams.forEach((s) => s.close())) };
    [reading, connected] = [true, false];
    streams.push(watch({ health: onHealth, end }));
    let read: Read | undefined;
    let jobs: Jobs | null;
    try {
      const resp = await post("/graphql", { method: "POST", body: JSON.stringify({ query: READ }), signal: stop.signal });
      read = resp.ok ? ((await resp.json()) as { data?: Read }).data : undefined;
      jobs = await readJobs(post);
      if (!read || !jobs) throw new Error("the board's reads failed");
    } catch {
      return end();
    }
    if (over) return;
    held = hold(read, jobs);
    const fold = (kind: Delta["kind"], changed: boolean) => void (changed && hand(kind));
    streams.push(
      follow<GqlChange>(TASK_CHANGES, "taskChanges", read.tasks.position, { change: (c) => fold("task", foldChange(held!, c)), end }, post),
      followJobs(jobs.position, { jobs: (list, error, beside) => fold("dags", foldJobs(held!, list, error, beside)), end }, post),
      openLedger("MERGED", { head: (page) => fold("ledgers", foldMarks(held!, page)), rows: (_, marks) => fold("ledgers", foldMarks(held!, marks)) }, post),
    );
    hand();
  }

  void connect();
  return {
    close() {
      stop.abort();
      clearTimeout(timer);
      clearTimeout(lost);
      open?.close();
    },
  };
}
