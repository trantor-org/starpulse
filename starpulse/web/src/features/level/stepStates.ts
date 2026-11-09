import type { LedgerRow, LedgerRun, RunStatus } from "../../api";

/** A step's state in a run; a template of one step takes the run's own. */
export const stepState = (run: LedgerRun, step: string, steps: readonly string[]): RunStatus =>
  run.steps[step] ?? (steps.length === 1 ? run.status : "not_started");

/** A merge's state for each step of a DAG's template, or null when it has no run of it. */
export function stepStates(row: LedgerRow | undefined, dag: string, steps: readonly string[]): Record<string, RunStatus> | null {
  const run = row?.runs[dag];
  return run ? Object.fromEntries(steps.map((n) => [n, stepState(run, n, steps)])) : null;
}
