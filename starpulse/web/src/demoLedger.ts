// The merge Ledger a self-contained demo page shows. A served page gets its rows from starpulse.ledger; a demo page has no server, so this builds the
// same rows from the snapshot's ties: the merges of the last day, a run of every tied DAG on each, and a new merge now and then.
// `?ms=` picks what the rows show: `live` (the default) keys every run by commit with the newest still running, `fail` pins one failed apply,
// `cross` adds another repository's merges and the pin bump that applies one, and `infer` is an install that declares no commit key, so time pairs every run.
import { MERGE_EVENT, tiesOf, type Tie } from "./ledger";
import type { ContractCheck, ContractReport, LedgerRow, LedgerRun, RunStatus, Snapshot } from "./types";

export type Scenario = "live" | "fail" | "cross" | "infer";
const SCENARIOS: Scenario[] = ["live", "fail", "cross", "infer"];

/** The scenario a page's address names, else `live`. */
export const scenarioOf = (search: string): Scenario => SCENARIOS.find((s) => s === new URLSearchParams(search).get("ms")) ?? "live";

/**
 * The contract report a demo page answers `/api/doctor` with, in the shape the server serves: a check for each cue, and for the `cross` scenario the
 * other repository. Every scenario but `infer` declares the commit keys; `infer` is the install that does not, which `starpulse doctor` warns of.
 */
export function demoContract(snap: Snapshot, scenario: Scenario): ContractReport {
  const cues = [...new Set((snap.cues ?? []).map((c) => c.dag))];
  const checks: ContractCheck[] = cues.map((dag) => scenario === "infer"
    ? { check: `cue:${dag}`, status: "warn", reason: `${dag} has no [runs.commit] after key, so its runs are time-inferred against merges` }
    : { check: `cue:${dag}`, status: "pass", reason: `${dag} declares AFTER, BEFORE, FORCE` });
  if (scenario === "cross") checks.push({ check: "repo:skills", status: "pass", reason: "skills is a submodule" });
  return { ok: checks.every((c) => c.status !== "fail"), checks };
}

/** Seconds before now each demo merge landed: eight in the first five hours, then one every 18 minutes to the edge of the day, so there are pages to load. */
const AGO = [20, 420, 1140, 2460, 4200, 7200, 12000, 18000, ...Array.from({ length: 60 }, (_, k) => 19_100 + k * 1100)];
const iso = (sec: number) => (sec ? new Date(sec * 1000).toISOString().replace(/\.\d+Z$/, "Z") : "");
const sha = (n: number) => (0xa1b2c3d4e5 + n * 0x3f1d27).toString(16).padStart(10, "0").slice(-10);
const stepsOf = (snap: Snapshot, dag: string) => snap.dags.find((d) => d.name === dag)?.steps.map((s) => s.name) ?? [];

/** A run of `tie` on a merge at `at`: succeeded, or `live` while it works through its steps, or `failed` at its middle step. */
function runOf(snap: Snapshot, tie: Tie, at: number, i: number, scenario: Scenario, state: "done" | "running" | "queued" | "failed"): LedgerRun {
  const names = stepsOf(snap, tie.dag), start = at + (tie.role === "writer" ? 2 : 6), cue = tie.role === "cue";
  const mid = Math.min(1, names.length - 1), status: RunStatus = state === "done" ? "succeeded" : state;
  const stepAt = (k: number): RunStatus => (status === "succeeded" ? "succeeded" : status === "queued" || k > mid ? "not_started" : k < mid ? "succeeded" : status);
  const steps: Record<string, RunStatus> = Object.fromEntries(names.map((n, k) => [n, stepAt(k)]));
  // an apply that was not needed is skipped on every other merge, so the steps a cue applies only sometimes are known
  if (cue && status === "succeeded" && names.length > 2 && i % 2) steps[names[1]] = "skipped";
  const took = tie.role === "writer" ? 18 + ((i * 5) % 20) : 40 + ((i * 11) % 50);
  return {
    runId: `${tie.dag}-${i}`, status, startedAt: status === "queued" ? "" : iso(start), finishedAt: status === "succeeded" || status === "failed" ? iso(start + took) : "", steps,
    step: status === "running" ? names[mid] ?? "" : "", inferred: scenario === "infer", ambiguous: scenario === "infer" && cue && i % 3 === 1 ? 1 : 0,
  };
}

/** The Ledger of merges the demo shows, newest first; none when no DAG is tied to the merge. */
export function demoLedger(snap: Snapshot, now: number, scenario: Scenario): LedgerRow[] {
  const ties = tiesOf(snap, MERGE_EVENT);
  if (!ties.length) return [];
  const rows = AGO.map((ago, i): LedgerRow => {
    const at = now - ago, last = ties.filter((t) => t.role === "cue").at(-1)?.dag, failing = scenario === "fail" && i === 2, fails: LedgerRow["fails"] = {};
    const runs = Object.fromEntries(ties.map((t) => {
      const state = i === 0 ? (t.role === "cue" ? "running" : "done") : failing && t.dag === last ? "failed" : "done";
      const run = runOf(snap, t, at, i, scenario, state);
      if (state === "failed") fails[t.dag] = { runId: run.runId, step: Object.entries(run.steps).find(([, s]) => s === "failed")?.[0] ?? "", startedAt: run.startedAt, finishedAt: run.finishedAt, resolves: t.resolves, resolved: null };
      return [t.dag, run];
    }));
    return { key: sha(i), at, tasks: [`DEMO-${i + 1}`], sha: sha(i), pr: { repo: "trantor", number: 300 - i, url: "#" }, runs, fails, pinned: failing };
  });
  if (scenario !== "cross") return rows;
  // another repository's merge is applied only when a later merge of this one bumps its pin; the newest is still waiting for one
  const bumpAt = now - 150, bump: LedgerRow = {
    key: sha(5040), at: bumpAt, tasks: [], sha: sha(5040), pr: { repo: "trantor", number: 331, url: "#" }, applies: [sha(5041)], fails: {}, pinned: false,
    runs: Object.fromEntries(ties.map((t) => [t.dag, runOf(snap, t, bumpAt, 40, scenario, "done")])),
  };
  const kid = (n: number, ago: number, appliedBy: string | null): LedgerRow => ({ key: sha(n), at: now - ago, tasks: [`DEMO-${n}`], sha: sha(n), pr: { repo: "skills", number: n, url: "#" }, appliedBy, runs: {}, fails: {}, pinned: false });
  return [...rows, bump, kid(5041, 540, bump.key), kid(5042, 30, null)].sort((a, b) => b.at - a.at);
}

/** `rows` after a merge lands at `now`: the runs in flight finish (a queued one as if it started 6 s after its merge), and the new merge's writer runs while its cues queue. Returns new rows; `rows` is left as it was. */
export function arriveMerge(snap: Snapshot, rows: LedgerRow[], now: number): LedgerRow[] {
  const ties = tiesOf(snap, MERGE_EVENT), next = structuredClone(rows);
  for (const row of next)
    for (const run of Object.values(row.runs))
      if (run.status === "running" || run.status === "queued") Object.assign(run, { status: "succeeded", step: "", startedAt: run.startedAt || iso(row.at + 6), finishedAt: iso(now), steps: Object.fromEntries(Object.keys(run.steps).map((n) => [n, "succeeded"])) });
  const n = rows.length + 6000, writer: Record<string, LedgerRun> = {};
  for (const t of ties) {
    const names = stepsOf(snap, t.dag), live = t.role === "writer";
    writer[t.dag] = {
      runId: `${t.dag}-${n}`, status: live ? "running" : "queued", startedAt: live ? iso(now) : "", finishedAt: "", step: live ? names[0] ?? "" : "", inferred: false, ambiguous: 0,
      steps: Object.fromEntries(names.map((s, k) => [s, live && k === 0 ? "running" : "not_started"])),
    };
  }
  return [{ key: sha(n), at: now, tasks: [`DEMO-${n}`], sha: sha(n), pr: { repo: "trantor", number: 300 + n, url: "#" }, runs: writer, fails: {}, pinned: false }, ...next];
}
