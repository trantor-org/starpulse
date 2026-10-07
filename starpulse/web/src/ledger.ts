// The Ledger: one Board transition's occurrences with the DAGs tied to its event. A DAG is tied when it writes the event or a machine cues it;
// the frame lists the writer and then each cue, left to right, under the path the transition takes. Pure: it reads the snapshot's Board machine
// and cues, and says what a Ledger holds, never how it is drawn.
import type { Fold } from "./levels";
import type { Snapshot } from "./types";

/** The Board event whose occurrences are pull request merges; every other event's are tasks entering a lane. */
export const MERGE_EVENT = "MERGED";

/** What a Ledger reads: the Board machine and the cues. */
export type Source = Pick<Snapshot, "flows" | "cues">;

/** A DAG tied to the event: the one that writes it (`on` its trigger) or a cue (`on` the occasion it runs, `resolves` how its failure clears). */
export interface Tie {
  dag: string;
  role: "writer" | "cue";
  on: string;
  resolves: "forced" | "next" | null;
}

export interface Ledger {
  event: string;
  from: string;
  to: string;
  /** What a row carries: a merge's pull request and commit, or a task. */
  rows: "merge" | "task";
  ties: Tie[];
}

const boardOf = (snap: Source) => snap.flows.find((f) => f.name === "board")?.machine;

/** The path a Board event takes between two states; null for an event the Board lacks or one that leaves its state where it was. */
export function pathOf(snap: Source, event: string): [string, string] | null {
  const t = boardOf(snap)?.transitions.find((x) => x.event === event && x.source !== x.target);
  return t ? [t.source, t.target] : null;
}

/** The DAGs tied to an event: the runs workflows that write it, then each DAG a cue names, in the order the machine declares them. */
export function tiesOf(snap: Source, event: string): Tie[] {
  const m = boardOf(snap), dags = new Set(m?.dagActors ?? []);
  const ties: Tie[] = (m?.writers?.[event] ?? []).filter((w) => dags.has(w.actor)).map((w) => ({ dag: w.actor, role: "writer", on: w.trigger, resolves: null }));
  for (const c of snap.cues ?? []) if (c.event === event && !ties.some((t) => t.dag === c.dag)) ties.push({ dag: c.dag, role: "cue", on: c.on, resolves: c.resolves ?? null });
  return ties;
}

/**
 * The Ledger a fold level draws, or null when its path carries no event a DAG is tied to. A fold opened from one event names it; a fold drilled
 * from the Board names the event of its path that most of its DAGs are tied to.
 */
export function ledgerOf(snap: Source, fold: Fold): Ledger | null {
  const path = fold.path, m = boardOf(snap);
  if (!path || !m) return null;
  const events = [...new Set(m.transitions.filter((t) => t.source === path[0] && t.target === path[1]).map((t) => t.event))];
  const share = (e: string) => tiesOf(snap, e).filter((t) => fold.dags.includes(t.dag)).length;
  const event = fold.event && events.includes(fold.event) ? fold.event : events.sort((a, b) => share(b) - share(a))[0];
  if (!event || !share(event)) return null;
  return { event, from: path[0], to: path[1], rows: event === MERGE_EVENT ? "merge" : "task", ties: tiesOf(snap, event) };
}
