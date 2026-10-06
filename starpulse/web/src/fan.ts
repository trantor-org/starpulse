// A DAG's runs in flight, as the panel lists them: one row per run, the queue they share and what each step holds.
import type { ActiveRun, Dag, Pool, RunStatus } from "./types";

/** Seconds a finished run's row stays in its outcome colour; a failed run's stays twice as long. */
export const LINGER_S = 6;
export const LINGER_FAILED_S = 12;
/** Seconds a row flashes after its run enters a step. */
export const FLASH_S = 1.2;

export interface Ended {
  run: ActiveRun;
  outcome: "succeeded" | "failed";
  at: number;
}

/** What the panel remembers of one DAG between snapshots: the runs it last saw, when each moved, and the runs that just ended. */
export interface Fan {
  primed: boolean;
  seen: Record<string, ActiveRun>;
  moved: Record<string, number>;
  ended: Record<string, Ended>;
}

export interface FanRow {
  id: string;
  task: string | null;
  state: "running" | "queued" | "succeeded" | "failed";
  strip: { name: string; status: RunStatus }[];
  step: string;
  inStep: number;
  elapsed: number;
  flash: boolean;
}

export interface QueueRow {
  /** The pool's name without its instance prefix. */
  pool: string;
  running: number;
  cap: number;
  queued: number;
  /** How many of the running runs are this DAG's. */
  mine: number;
  full: boolean;
}

export const emptyFan = (): Fan => ({ primed: false, seen: {}, moved: {}, ended: {} });

const seconds = (iso: string) => (iso ? Date.parse(iso) / 1000 : 0);
const lingers = (e: Ended, now: number) => now - e.at < (e.outcome === "failed" ? LINGER_FAILED_S : LINGER_S);

/** How a run that left the DAG's active list ended: the DAG's own status when it is the latest run, else whether its last-seen steps held a failure. */
function outcome(dag: Dag, run: ActiveRun): Ended["outcome"] {
  if (dag.runId === run.runId && dag.status !== "running") return dag.status === "succeeded" ? "succeeded" : "failed";
  return Object.values(run.steps).includes("failed") ? "failed" : "succeeded";
}

/** The fan after the DAG's next listing: a run it has not seen or that entered a step is marked moved, a run that left the list ended, and an ended run past its linger gone. */
export function track(prev: Fan, dag: Dag, now: number): Fan {
  const seen: Fan["seen"] = {}, moved: Fan["moved"] = {}, ended: Fan["ended"] = {};
  for (const run of dag.active ?? []) {
    const before = prev.seen[run.runId];
    seen[run.runId] = run;
    moved[run.runId] = !prev.primed ? -Infinity : before && before.step === run.step && before.status === run.status ? prev.moved[run.runId] : now;
  }
  for (const [id, e] of Object.entries(prev.ended)) if (lingers(e, now)) ended[id] = e;
  for (const [id, run] of Object.entries(prev.seen)) if (!seen[id] && run.status !== "queued") ended[id] = { run, outcome: outcome(dag, run), at: now };
  return { primed: true, seen, moved, ended };
}

const stripOf = (dag: Dag, steps: ActiveRun["steps"]) => dag.steps.map((s) => ({ name: s.name, status: steps[s.name] ?? ("not_started" as const) }));
/** The Board task a run id carries (`deliver-agent-task-2787-…` carries TASK-2787): the longest id of `tasks` that sits in it whole, not as the front of a longer number. */
function taskOf(runId: string, tasks: readonly string[]): string | null {
  const rid = runId.toLowerCase();
  let best: string | null = null;
  for (const id of tasks) {
    const at = rid.indexOf(id.toLowerCase());
    if (at >= 0 && !/[a-z0-9]/.test(rid[at + id.length] ?? "") && id.length > (best?.length ?? 0)) best = id;
  }
  return best;
}

/** One row per run in flight and per run that just ended, longest-running first, then the queued runs; `tasks` are the Board's task ids a run id may name. */
export function fanRows(fan: Fan, dag: Dag, now: number, tasks: readonly string[] = []): FanRow[] {
  const live = (dag.active ?? []).filter((r) => r.status !== "queued").map((run): FanRow => ({
    id: run.runId,
    task: taskOf(run.runId, tasks),
    state: "running",
    strip: stripOf(dag, run.steps),
    step: run.step,
    inStep: run.stepStartedAt ? now - seconds(run.stepStartedAt) : 0,
    elapsed: now - seconds(run.startedAt),
    flash: now - (fan.moved[run.runId] ?? -Infinity) < FLASH_S,
  }));
  const done = Object.values(fan.ended).filter((e) => lingers(e, now)).map((e): FanRow => {
    const failed = e.outcome === "failed", steps = e.run.steps;
    const marked = failed && !Object.values(steps).includes("failed") && e.run.step ? { ...steps, [e.run.step]: "failed" as const } : steps;
    return {
      id: e.run.runId,
      task: taskOf(e.run.runId, tasks),
      state: e.outcome,
      strip: failed ? stripOf(dag, marked) : dag.steps.map((s) => ({ name: s.name, status: "succeeded" as const })),
      step: e.run.step,
      inStep: 0,
      elapsed: e.at - seconds(e.run.startedAt),
      flash: now - e.at < FLASH_S,
    };
  });
  const waiting = (dag.active ?? []).filter((r) => r.status === "queued").map((run): FanRow => ({
    id: run.runId,
    task: taskOf(run.runId, tasks),
    state: "queued",
    strip: stripOf(dag, run.steps),
    step: "",
    inStep: 0,
    elapsed: 0,
    flash: false,
  }));
  return [...live, ...done].sort((a, b) => b.elapsed - a.elapsed).concat(waiting);
}

/** The pool the DAG runs on against its cap, or null when its adapter reports none. */
export function queueRow(dag: Dag, pools: Pool[] | undefined): QueueRow | null {
  const pool = dag.pool ? pools?.find((p) => p.name === dag.pool) : undefined;
  if (!pool) return null;
  return {
    pool: pool.name.slice(pool.name.indexOf("/") + 1),
    running: pool.running,
    cap: pool.cap,
    queued: pool.queued,
    mine: (dag.active ?? []).filter((r) => r.status === "running").length,
    full: pool.cap > 0 && pool.running >= pool.cap,
  };
}

/** How many of the DAG's running runs are in the step. */
export const stepRuns = (dag: Dag, step: string): number => (dag.active ?? []).filter((r) => r.status === "running" && r.step === step).length;
