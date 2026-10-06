// What the drawing reads: the pushed snapshot merged into one sky, and the
// moves the page plays. The approved mockup replayed a saved hour; the page
// plays each move once, when the stream first delivers it.
import { tree, type Tree } from "./levels";
import type { Cue, Dag, FlowSnapshot, Pull, RawAgent, Snapshot, Writer } from "./types";

/** Seconds one move takes to cross its path, the arrival rings, and a finished DAG's flare. */
export const TRAVEL = 3;
export const PULSE = 1.8;
export const FLARE = 4;
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
  dagBy: Record<string, Dag>;
  writers: Record<string, Writer[]>;
  launches: Launch[];
  cues: Cue[];
  groups: Group[];
  dagGroup: Record<string, string>;
  runnable: Set<string>;
  boardUrl: string | null;
  /** What the board writes beyond moves; absent for a board that only reads. */
  capabilities?: { edit: boolean; archive: boolean };
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
  settled: Record<string, string>;
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

export function merge(snap: Snapshot): Sky {
  const boardTasks = new Map((snap.flows.find((f) => f.name === "board")?.agents ?? []).map((a) => [a.id, a]));
  const flows = Object.fromEntries(snap.flows.map((f) => [f.name, f.name === "board" ? f : { ...f, agents: f.agents.map((a) => joined(a, boardTasks)) }]));
  const board = flows.board ?? EMPTY, t = tree(snap), groups = (snap.domains ?? []).map((d) => ({ name: d.name, dags: d.dags.map((x) => x.name) }));
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
    dagBy: Object.fromEntries(snap.dags.map((d) => [d.name, d])),
    writers: board.machine.writers ?? {},
    launches: Object.entries(board.machine.launches ?? {}).map(([dag, l]) => ({ dag, skill: l.skill, flow: l.flow })),
    cues: snap.cues ?? [],
    groups,
    dagGroup: Object.fromEntries(groups.flatMap((g) => g.dags.map((d) => [d, g.name]))),
    runnable: new Set((snap.domains ?? []).flatMap((d) => d.dags.filter((x) => x.runSafe).map((x) => x.name))),
    boardUrl: snap.boardUrl ?? null,
    capabilities: snap.capabilities,
    tree: t,
    subs: t.subs,
    child,
    latest,
    pulls: snap.pulls ?? {},
    claims: snap.claims ?? {},
    settled: snap.settled,
    error: snap.error,
    reading: !!snap.reading,
  };
}

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

/**
 * The moves the page plays, on the page's clock. A step from before the page
 * loaded keeps the time it happened; a step the stream first delivers plays then, and a
 * burst of steps between two snapshots plays one travel apart, so each still draws.
 */
export class Moves {
  events: Move[] = [];
  /** When each DAG's latest run ended, on the page's clock. */
  flare: Record<string, number> = {};
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
    this.events = this.events.filter((e) => e.at >= t - HOUR).sort((a, b) => a.at - b.at);
    this.prev = S;
  }
}
