// What the drawing reads: the pushed snapshot merged into one sky, and the
// moves the page plays. The approved mockup replayed a saved hour; the page
// plays each move once, when the stream first delivers it.
import { stepRings, type StepRing } from "../features/fanout/fanout";
import { tree, type Tree } from "./levels";
import type { Capabilities, Cue, Dag, FlowSnapshot, LedgerRow, MachineEntry, MachinePage, MergeStrip, Pool, Pull, RawAgent, Settled, Snapshot, Writer } from "../api";

/** Seconds one move takes to cross its path, the arrival rings, and a finished DAG's flare. */
export const TRAVEL = 3;
export const PULSE = 1.8;
export const FLARE = 4;
/** Seconds a step's ring takes to fade. */
export const RING = 1.1;
/** Moves older than this are forgotten. */
export const HOUR = 3600;

export interface Launch {
  dag: string;
  skill: string;
  flow: string | null;
}
export interface Group {
  name: string;
  dags: string[];
}
export interface ChildLink {
  flow: string;
  when: string;
}
export interface Sky {
  now: number;
  flows: Record<string, FlowSnapshot>;
  board: FlowSnapshot;
  dags: Dag[];
  /** The concurrency pools the DAGs run on; empty when the adapter reports none. */
  pools: Pool[];
  dagBy: Record<string, Dag>;
  writers: Record<string, Writer[]>;
  launches: Launch[];
  cues: Cue[];
  groups: Group[];
  dagGroup: Record<string, string>;
  runnable: Set<string>;
  boardUrl: string | null;
  /** What the board writes beyond moves; absent for a board that only reads. */
  capabilities?: Capabilities;
  /** The Backlog.md project serve found beside the config while it shows its own board, and how to switch to it. */
  hint: string | null;
  tree: Tree;
  /** The lifecycle machines each Board state opens into; the first is the state's own. */
  subs: Record<string, string[]>;
  /** The machine that opens under a machine's state, and when it runs. */
  child: Record<string, Record<string, ChildLink>>;
  /** Each Backlog task's latest session on a lifecycle machine: the machine it is in and the state that machine left it in. */
  latest: Record<string, { flow: string; state: string; at: number }>;
  /** Each open task's pull requests, by task id. */
  pulls: Record<string, Pull[]>;
  /** Each task's latest In Progress claim the board writer refused an agent, and when. */
  claims: Record<string, { reason: string; at: number }>;
  settled: Record<string, Settled>;
  /** Each Ledger event's rows, newest first; empty when the server sent none. */
  ledgers: Record<string, LedgerRow[]>;
  /** The merge Ledger's 24-hour strip; null when the server sent none. */
  mergeStrip: MergeStrip | null;
  /** The pinned merges the Ledger's newest page leaves out. */
  mergePins: LedgerRow[];
  /** The first page of the machine ledger's rows; null when the server sent none, which shows every machine. */
  machinePage: MachinePage | null;
  /** The last 24 hours of machine entries, oldest first; empty when the server sent none. */
  machineEntries: MachineEntry[];
  /** The day's arrivals on each starting and terminal Board state: tasks created, or settled there, since local midnight. */
  today: Record<string, RawAgent[]>;
  error: string | null;
  /** The server was still reading its board, so this sky's Board is partial. */
  reading: boolean;
}

const EMPTY: FlowSnapshot = { name: "board", machine: { states: [], transitions: [] }, agents: [] };

/** A machine's task with what the Board knows of it (title, profile, labels, dependencies, pull requests, description) laid over the machine's own place for it. */
const joined = (a: RawAgent, board: Map<string, RawAgent>): RawAgent => {
  const b = board.get(a.task ?? a.id);
  return b ? { ...a, title: b.title, model: b.model || a.model, labels: b.labels, dependencies: b.dependencies, prs: b.prs, description: b.description } : a;
};

/**
 * A machine's tasks at one Board state. A flow several states open (the mapped CI machine under In Progress and Review) shows each
 * state only the tasks whose Board task sits there; a flow one state opens, or a level above any state, shows them all.
 */
export function hosted(sky: Pick<Sky, "flows" | "board" | "tree">, flow: string, host?: string): RawAgent[] {
  const agents = sky.flows[flow]?.agents ?? [];
  if (host === undefined || Object.values(sky.tree.subs).filter((fs) => fs.includes(flow)).length < 2) return agents;
  const state = boardStates(sky.board);
  return agents.filter((a) => state.get(a.task ?? a.id) === host);
}

/** Each Board task's state by id, built once per Board: a frame asks it of every moon it draws. */
const statesOf = new WeakMap<FlowSnapshot, Map<string, string>>();
function boardStates(board: FlowSnapshot): Map<string, string> {
  let state = statesOf.get(board);
  if (!state) statesOf.set(board, (state = new Map(board.agents.map((a) => [a.id, a.state]))));
  return state;
}

/** Local midnight today, in epoch seconds. */
export const midnight = (now = new Date()) => new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;

/** A Board state that counts the day's arrivals rather than the tasks in it: where tasks start, or a final state where they end. */
export const daily = (s: { initial: boolean; final: boolean }) => s.initial || s.final;

/** The tasks created since `since` on each starting state, and those settled since then on the terminal state each settled in. */
function arrivals(board: FlowSnapshot, settled: Record<string, Settled>, since: number): Record<string, RawAgent[]> {
  const out: Record<string, RawAgent[]> = {}, dot = (id: string, title: string, model: string, state: string): RawAgent => ({ id, title, model, state, today: true });
  const settledDots = Object.entries(settled);
  for (const s of board.machine.states.filter(daily)) {
    const list = s.initial
      ? [...board.agents.filter((a) => (a.created ?? -Infinity) >= since).map((a) => dot(a.id, a.title, a.model, s.id)),
          ...settledDots.filter(([, e]) => (e.created ?? -Infinity) >= since).map(([id, e]) => dot(id, e.title, e.model, s.id))]
      : [...board.agents.filter((a) => a.state === s.id && (a.entered ?? -Infinity) >= since).map((a) => dot(a.id, a.title, a.model, s.id)),
          ...settledDots.filter(([, e]) => e.state === s.id && (e.at ?? -Infinity) >= since).map(([id, e]) => dot(id, e.title, e.model, s.id))];
    if (list.length) out[s.id] = list;
  }
  return out;
}

export function merge(snap: Snapshot, since = midnight()): Sky {
  const boardTasks = new Map((snap.flows.find((f) => f.name === "board")?.agents ?? []).map((a) => [a.id, a]));
  const flows = Object.fromEntries(snap.flows.map((f) => [f.name, f.name === "board" ? f : { ...f, agents: f.agents.map((a) => joined(a, boardTasks)) }]));
  const board = flows.board ?? EMPTY, t = tree(snap), groups = (snap.domains ?? []).map((d) => ({ name: d.name, dags: d.dags.map((x) => x.name) }));
  // the writers the Star Map draws on a Board path are the ones that are no DAG; a DAG's own are on the DAGs view and a Ledger
  const actors = new Set([...(board.machine.dagActors ?? []), ...snap.dags.map((d) => d.name)]);
  const child: Sky["child"] = {}, latest: Sky["latest"] = {}, active: Record<string, number> = {};
  for (const f of Object.values(flows))
    if (f.name !== "board")
      for (const a of f.agents)
        if (a.task && (active[a.task] === undefined || (a.active ?? 0) > active[a.task])) [active[a.task], latest[a.task]] = [a.active ?? 0, { flow: f.name, state: a.state, at: a.active ?? 0 }];
  for (const [parent, kids] of Object.entries(t.children)) for (const c of kids) (child[parent] ??= {})[c.state] = { flow: c.flow, when: c.when && `while ${c.when}` };
  return {
    now: snap.now,
    flows,
    board,
    dags: snap.dags,
    pools: snap.pools ?? [],
    dagBy: Object.fromEntries(snap.dags.map((d) => [d.name, d])),
    writers: Object.fromEntries(Object.entries(board.machine.writers ?? {}).map(([event, ws]) => [event, ws.filter((w) => !actors.has(w.actor))])),
    launches: Object.entries(board.machine.launches ?? {}).map(([dag, l]) => ({ dag, skill: l.skill, flow: l.flow })),
    cues: snap.cues ?? [],
    groups,
    dagGroup: Object.fromEntries(groups.flatMap((g) => g.dags.map((d) => [d, g.name]))),
    runnable: new Set((snap.domains ?? []).flatMap((d) => d.dags.filter((x) => x.runSafe).map((x) => x.name))),
    boardUrl: snap.boardUrl ?? null,
    capabilities: snap.capabilities ?? undefined,
    hint: snap.hint ?? null,
    tree: t,
    subs: t.subs,
    child,
    latest,
    pulls: snap.pulls ?? {},
    claims: snap.claims ?? {},
    settled: snap.settled,
    ledgers: snap.ledgers ?? {},
    mergeStrip: snap.mergeStrip ?? null,
    mergePins: snap.mergePins ?? [],
    machinePage: snap.machinePage ?? null,
    machineEntries: snap.machineStrip?.entries ?? [],
    today: arrivals(board, snap.settled, since),
    error: snap.error,
    reading: !!snap.reading,
  };
}

/** `sky` with the Ledger fields `snap` now carries; a Ledger delta changes nothing else, so every other part is the object `sky` held. */
export function withLedgers(sky: Sky, snap: Snapshot): Sky {
  return { ...sky, ledgers: snap.ledgers ?? {}, mergeStrip: snap.mergeStrip ?? null, mergePins: snap.mergePins ?? [] };
}

/** A Board state's count: a starting state's is the day's arrivals alone, as it is a concept no task stays in; any other's is the tasks in it,
 * and on a terminal state the day's arrivals there not already in it. */
export function stateCount(sky: Sky, sid: string): number {
  if (sky.board.machine.states.find((s) => s.id === sid)?.initial) return sky.today[sid]?.length ?? 0;
  const here = new Set(sky.board.agents.filter((a) => a.state === sid).map((a) => a.id));
  return here.size + (sky.today[sid] ?? []).filter((t) => !here.has(t.id)).length;
}

/** How a Board state's count reads: `n`, or on a starting or terminal state `N today`, with every task drawn first when some did not arrive today. */
export const countText = (n: number, today?: number) => (today === undefined ? `${n}` : n > today ? `${n} · ${today} today` : `${today} today`);

/** One step a task takes: from null is where it was first seen. */
export interface Move {
  flow: string;
  task?: string | null;
  at: number;
  event: string;
  to: string;
  from: string | null;
}

const finished = (d: Dag) => (d.finishedAt ? Date.parse(d.finishedAt) / 1000 : NaN);

/** A run's entry into a step, or its end in one, as the ring it draws. */
export interface StepMove extends StepRing {
  dag: string;
  at: number;
}

/**
 * The moves the page plays, on the page's clock. A step from before the page
 * loaded keeps the time it happened; a step the stream first delivers plays then, and a
 * burst of steps between two snapshots plays one travel apart, so each still draws.
 */
export class Moves {
  events: Move[] = [];
  /** When each DAG's latest run ended, on the page's clock. */
  flare: Record<string, number> = {};
  /** The rings the steps of DAG glyphs are showing, on the page's clock: a run entering a step, or ending in it. */
  rings: StepMove[] = [];
  private seen = new Set<string>();
  private last: Record<string, number> = {};
  private prev: Sky | null = null;
  /** The snapshot clock last read and the page's clock less it; a delta keeps its snapshot's clock, so it keeps the offset taken then. */
  private clock = { now: NaN, off: 0 };

  /**
   * Read the next sky as a page load: what changed since the last one is placed at the time it happened, not queued to play. Board moves
   * carry no time of their own, so the ones from before are dropped and each task stands where the next sky puts it; a move still queued
   * to play after `now` is dropped too, and every task's queue starts afresh.
   */
  resync(now: number) {
    this.prev = null;
    this.last = {};
    this.events = this.events.filter((e) => e.flow !== "board" && e.at <= now);
  }

  observe(S: Sky, t: number) {
    if (this.prev?.reading) this.resync(t); // the Board the server finished reading is placed as a page load, not moved onto from a partial one
    if (S.now !== this.clock.now) this.clock = { now: S.now, off: t - S.now };
    const off = this.clock.off, prev = this.prev, add = (m: Move, key: string) => {
      if (m.at >= t - HOUR) this.events.push(m);
      this.last[key] = Math.max(this.last[key] ?? -Infinity, m.at);
    };
    // a move waits for the task's last one to land, but never more than one travel: a burst shows its latest state, not a replay
    const queue = (key: string) => Math.min(Math.max(t, (this.last[key] ?? -Infinity) + TRAVEL), t + TRAVEL);
    for (const f of Object.values(S.flows)) {
      if (f.name === "board") continue;
      for (const s of f.agents)
        (s.trail ?? []).forEach((st, i, trail) => {
          const id = `${f.name}|${s.id}|${st.at}|${st.event}`;
          if (this.seen.has(id)) return;
          this.seen.add(id);
          const fresh = prev !== null && st.at > prev.now;
          add({ flow: f.name, task: s.id, at: fresh ? queue(s.id) : st.at + off, event: st.event, to: st.state, from: i ? trail[i - 1].state : null }, s.id);
        });
    }
    if (prev) {
      const was = Object.fromEntries(prev.board.agents.map((a) => [a.id, a.state]));
      for (const a of S.board.agents) {
        const from = was[a.id] ?? null;
        if (from === a.state) continue;
        const event = from ? (S.board.machine.transitions.find((x) => x.source === from && x.target === a.state)?.event ?? "MOVE") : "CREATE";
        add({ flow: "board", task: a.id, at: queue(a.id), event, from, to: a.state }, a.id);
      }
    }
    for (const d of S.dags) {
      const f = finished(d);
      if (Number.isNaN(f)) continue;
      const before = prev?.dagBy[d.name];
      if (!prev) this.flare[d.name] = f + off;
      else if (!before || finished(before) !== f) this.flare[d.name] = t;
    }
    this.rings = this.rings.filter((r) => t - r.at < RING);
    if (prev) for (const d of S.dags) for (const r of stepRings(prev.dagBy[d.name], d)) this.rings.push({ dag: d.name, ...r, at: t });
    this.events = this.events.filter((e) => e.at >= t - HOUR).sort((a, b) => a.at - b.at);
    this.prev = S;
  }
}
