// The Ledger: one Board transition's occurrences with the DAGs tied to its event. A DAG is tied when it writes the event or a machine cues it;
// the frame lists the writer and then each cue, left to right, under the path the transition takes. Pure: it reads the snapshot's Board machine
// and cues, and says what a Ledger holds, never how it is drawn.
import type { Fold } from "./levels";
import type { LedgerRow, LedgerRun, RunStatus, Snapshot } from "./types";

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

// ---- A merge row: what the Ledger prints for one merge under one tied DAG, and the state it summarises to.

/** How a run was paired with its merge: by its commit, by time alone, or by time with another merge in its window. */
export type Mark = "keyed" | "inferred" | "ambiguous";

export const markOf = (run: LedgerRun | undefined): Mark => (!run || !run.inferred ? "keyed" : run.ambiguous > 0 ? "ambiguous" : "inferred");

/** The state a cell or row shows: a run's status, or `waiting` for another repository's merge no pin bump has applied. */
export type RowState = RunStatus | "waiting";

export interface Line {
  /** The cell's headline: how the run went. */
  main: string;
  /** Its sub-line: what the run wrote, applied or when it started. */
  sub: string;
  state: RowState | null;
  mark: Mark;
}

export interface LineCtx {
  event: string;
  /** Epoch seconds the page draws at: a running run has run until then. */
  now: number;
  /** A clock time of an epoch second, in the viewer's format. */
  hm: (sec: number) => string;
  /** The steps of this DAG that some loaded row's run skipped: the ones a run applies only when its merge needs them. */
  optional: ReadonlySet<string>;
  /** The loaded row with a key, for a pin bump's commit. */
  by: (key: string) => LedgerRow | undefined;
}

const epoch = (iso: string) => (iso ? Date.parse(iso) / 1000 : 0);

/** A duration in seconds: `42 s`, then `1:40`. */
export function dur(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The steps of a DAG some row's run skipped, across the loaded rows. */
export function optionalSteps(rows: readonly LedgerRow[], dag: string): Set<string> {
  const out = new Set<string>();
  for (const r of rows) for (const [step, status] of Object.entries(r.runs[dag]?.steps ?? {})) if (status === "skipped") out.add(step);
  return out;
}

/** The optional steps a run applied, without their `apply_` prefix: `deploy, skills_a`. */
export function shortApplied(run: LedgerRun, optional: ReadonlySet<string>): string {
  return Object.entries(run.steps).filter(([step, status]) => optional.has(step) && status === "succeeded").map(([step]) => step.replace(/^apply_/, "")).join(", ");
}

/** What one merge shows under one tied DAG. */
export function statusLine(row: LedgerRow, tie: Tie, run: LedgerRun | undefined, ctx: LineCtx): Line {
  if (!run) {
    if (row.appliedBy === undefined) return { main: "no run yet", sub: "", state: null, mark: "keyed" };
    const bump = row.appliedBy ? ctx.by(row.appliedBy) : undefined;
    return bump
      ? { main: `applied by its pin bump ${(bump.sha ?? bump.key).slice(0, 7)}`, sub: ctx.hm(bump.at), state: "waiting", mark: "keyed" }
      : { main: "waits for its pin bump", sub: "", state: "waiting", mark: "keyed" };
  }
  const start = epoch(run.startedAt), took = epoch(run.finishedAt) - start;
  const main =
    run.status === "queued" || run.status === "not_started" ? "queued"
    : run.status === "running" ? `${run.step || "running"} · ${dur(ctx.now - start)}`
    : run.status === "failed" ? `✕ ${[row.fails[tie.dag]?.step, dur(took)].filter(Boolean).join(" · ")}`
    : run.status === "succeeded" ? `✓ ${dur(took)}`
    : run.status.replace("_", " ");
  let sub = tie.role === "writer" ? `${ctx.event} ${ctx.hm(row.at)}` : shortApplied(run, ctx.optional) || ctx.hm(start);
  const mark = markOf(run);
  if (mark !== "keyed") sub = `≈ ${mark === "ambiguous" ? `${run.ambiguous + 1} in window · ` : ""}${sub}`;
  return { main, sub, state: run.status, mark };
}

const RANK: RunStatus[] = ["failed", "running", "queued", "succeeded"];

/** The state a merge row summarises to: its worst run; for another repository's merge, its pin bump's, and `waiting` until one applies it. */
export function worst(row: LedgerRow, bump?: LedgerRow): RowState {
  if (row.appliedBy !== undefined) return row.appliedBy && bump ? worst(bump) : "waiting";
  const have = Object.values(row.runs).map((r) => r.status);
  return RANK.find((s) => have.includes(s)) ?? "succeeded";
}

/**
 * The keys of `rows` a last look at the Ledger did not hold: the merges that just arrived. The first look (`seen` null) holds none, so a page opened or
 * a Ledger switched to shows its rows still; the caller replaces `seen` with every key it has now.
 */
export function freshKeys(seen: ReadonlySet<string> | null, rows: readonly LedgerRow[]): string[] {
  return seen ? rows.filter((r) => !seen.has(r.key)).map((r) => r.key) : [];
}
