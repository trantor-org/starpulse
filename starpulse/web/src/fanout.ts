// What a DAG's fan-out adds: the navigator's rows of concurrency pools, the Recent feed's lines for the runs that start, queue, change step
// and end, and on each DAG's glyph the badge, step status, tooltip line and rings. All read the runs contract's `pools` and each DAG's
// `active` runs, never a simulation.
import { esc } from "./panels";
import type { ActiveRun, Dag, Pool } from "./types";

/** How many run lines the feed keeps. */
const KEEP = 12;

const bare = (name: string) => name.slice(name.indexOf("/") + 1);

/** The names as drawn: bare, unless another instance runs one by the same bare name. */
const labelled = (names: string[]): string[] => {
  const count = new Map<string, number>();
  for (const n of names) count.set(bare(n), (count.get(bare(n)) ?? 0) + 1);
  return names.map((n) => (count.get(bare(n)) === 1 ? bare(n) : n));
};

/** One pool as the navigator draws it. */
export interface PoolRow {
  name: string;
  label: string;
  /** `running/cap`. */
  count: string;
  /** `+queued` while runs wait, else empty. */
  queued: string;
  /** Running at its cap: drawn red. */
  full: boolean;
  /** Something runs: drawn in the activity colour. */
  busy: boolean;
  /** The meter's fill, 0 to 100. */
  pct: number;
}

export function poolRows(pools: Pool[] | undefined): PoolRow[] {
  const list = pools ?? [], labels = labelled(list.map((p) => p.name));
  return list.map((p, i) => ({
    name: p.name,
    label: labels[i],
    count: `${p.running}/${p.cap}`,
    queued: p.queued ? `+${p.queued}` : "",
    full: p.cap > 0 && p.running >= p.cap,
    busy: p.running > 0,
    pct: p.cap > 0 ? Math.min(100, (p.running / p.cap) * 100) : 0,
  }));
}

/** One run line of the feed: `who` is the DAG, `where` what the run did and for which task. */
export interface RunLine {
  key: string;
  at: number;
  who: string;
  what: "";
  where: string;
  /** Green for a run that succeeded, red for one that failed. */
  tone?: "ok" | "failed";
  /** Born after the page's first read, so the feed flashes it once. */
  fresh: true;
  runId: string;
  /** The task the run id embeds, which hovering the line lights; none when it embeds none. */
  task?: string;
  /** The DAG that ran it, which the line lights when it names no task. */
  dag: string;
}

/** The task a run id embeds (`deliver-agent-task-2787-…` is TASK-2787, a demo run's `…-demo-4` is DEMO-4), else the run id itself. */
const taskIn = (runId: string) => {
  const m = /(?:^|-)(task|demo)-(\d+)/i.exec(runId);
  return m ? `${m[1].toUpperCase()}-${m[2]}` : undefined;
};

/** How a run that left `active` ended: the DAG's own verdict when the run is its latest, else the steps the run was last seen in. */
function outcome(dag: Dag, last: ActiveRun): { what: string; tone: "ok" | "failed" } {
  if (dag.runId === last.runId) {
    if (dag.status === "succeeded") return { what: "succeeded", tone: "ok" };
    if (dag.status === "failed" || dag.status === "aborted") return { what: dag.status, tone: "failed" };
  }
  const failed = Object.entries(last.steps).find(([, s]) => s === "failed");
  return failed ? { what: `failed at ${failed[0]}`, tone: "failed" } : { what: "succeeded", tone: "ok" };
}

/**
 * The run lines of the Recent feed, found by comparing each snapshot's `active` runs with the last one's. Runs are followed by id, so
 * two runs of one DAG each write their own steps. The first read, and the first after a `resync`, announces nothing: a run
 * already in flight is not new.
 */
export class RunEvents {
  /** Newest first. */
  lines: RunLine[] = [];
  private prev: Map<string, ActiveRun> | null = null;
  private seq = 0;

  /** Forget what was seen, so the next read is a first read. */
  resync() {
    this.prev = null;
  }

  observe(dags: Dag[], at: number) {
    const now = new Map<string, ActiveRun>(), prev = this.prev;
    const labels = labelled(dags.map((d) => d.name)), names = new Map(dags.map((d, i) => [d.name, labels[i]]));
    for (const d of dags) for (const r of d.active ?? []) now.set(`${d.name}|${r.runId}`, r);
    this.prev = now;
    if (!prev) return;
    const add: RunLine[] = [];
    const line = (dag: Dag, runId: string, what: string, tone?: "ok" | "failed") => {
      const task = taskIn(runId);
      add.push({ key: `r${this.seq++}`, at, who: names.get(dag.name) ?? dag.name, what: "", where: `${what} · ${task ?? runId}`, tone, fresh: true, runId, task, dag: dag.name });
    };
    for (const d of dags) {
      for (const r of d.active ?? []) {
        const was = prev.get(`${d.name}|${r.runId}`);
        if (!was) line(d, r.runId, r.status === "queued" ? "queued" : "started");
        else if (was.status === "queued" && r.status !== "queued") line(d, r.runId, "started");
        else if (r.step && r.step !== was.step && r.status !== "queued") line(d, r.runId, r.step);
      }
      for (const [id, was] of prev) {
        if (!id.startsWith(`${d.name}|`) || now.has(id)) continue;
        const o = outcome(d, was);
        line(d, was.runId, o.what, o.tone);
      }
    }
    this.lines = [...add.reverse(), ...this.lines].slice(0, KEEP);
  }
}

/** The runs a DAG has running, and how many wait in its pool. */
const held = (dag: Pick<Dag, "active">) => ({
  running: (dag.active ?? []).filter((r) => r.status === "running"),
  queued: (dag.active ?? []).filter((r) => r.status === "queued").length,
});

/**
 * The badge a DAG's glyph carries while it has a run in flight or queued: its running runs over its pool's cap, `+q` for those waiting, and
 * `full` once the pool's running runs (any DAG's) fill its cap. Null while idle, or when the adapter reports no pool for the DAG.
 */
export function fanBadge(dag: Pick<Dag, "active" | "pool">, pools: Pool[] | undefined): { text: string; full: boolean } | null {
  const pool = pools?.find((p) => p.name === dag.pool), { running, queued } = held(dag);
  if (!pool || (!running.length && !queued)) return null;
  return { text: `${running.length}/${pool.cap}${queued ? ` +${queued}` : ""}`, full: pool.running >= pool.cap };
}

/**
 * A glyph step's status from the runs in flight: failed when a run failed in it, running while a run is in it, succeeded once a run is past it,
 * else not started. `fallback` (the DAG's latest run) stands while no run is in flight; a queued run has entered no step.
 */
export function stepStatus(dag: Pick<Dag, "active">, step: string, fallback: string): string {
  const runs = (dag.active ?? []).filter((r) => r.status !== "queued");
  if (!runs.length) return fallback;
  const of = (status: string) => runs.some((r) => r.steps[step] === status || (status === "running" && r.step === step));
  return of("failed") ? "failed" : of("running") ? "running" : of("succeeded") ? "succeeded" : "not_started";
}

/** The tooltip's fan-out lines: the runs this DAG has running against its pool's cap and those queued, then how the running ones spread over the steps. */
export function fanTip(dag: Pick<Dag, "active" | "pool">, pools: Pool[] | undefined): string {
  const pool = pools?.find((p) => p.name === dag.pool), { running, queued } = held(dag);
  if (!pool || (!running.length && !queued)) return "";
  const at = new Map<string, number>();
  for (const r of running) if (r.step) at.set(r.step, (at.get(r.step) ?? 0) + 1);
  const spread = [...at].sort((a, b) => b[1] - a[1]).map(([step, n]) => `${n} at ${esc(step)}`).join(" · ");
  return `<div class="k">${running.length} of ${pool.cap} running on queue ${esc(pool.name)}${queued ? ` · ${queued} queued` : ""}</div>${spread ? `<div class="k">${spread}</div>` : ""}`;
}

export interface StepRing {
  step: string;
  status: "running" | "succeeded" | "failed";
}

/**
 * The rings one listing raises over the last: amber on a step a run entered (a started run's first step included), and, for a run that left
 * `active` as the DAG's latest, green on the step it ended in or red on each step that failed. An ended run that is no longer the latest
 * carries no outcome, so it rings nothing. A DAG with no earlier listing was first seen, not moved.
 */
export function stepRings(before: Dag | undefined, after: Dag): StepRing[] {
  if (!before) return [];
  const rings = new Map<string, StepRing>(), add = (step: string, status: StepRing["status"]) => step && rings.set(`${step}|${status}`, { step, status });
  const now = new Map((after.active ?? []).map((r) => [r.runId, r]));
  for (const run of after.active ?? []) {
    const was = (before.active ?? []).find((r) => r.runId === run.runId);
    if (run.status === "running" && (was?.status !== "running" || was.step !== run.step)) add(run.step, "running");
  }
  for (const run of before.active ?? []) {
    if (now.has(run.runId) || after.runId !== run.runId) continue;
    if (after.status === "succeeded") add(run.step, "succeeded");
    else if (after.status === "failed") {
      const failed = after.steps.filter((s) => s.status === "failed");
      for (const s of failed.length ? failed : [{ name: run.step }]) add(s.name, "failed");
    }
  }
  return [...rings.values()];
}
