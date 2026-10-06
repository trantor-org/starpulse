// What a DAG's fan-out adds beside the glyph: the navigator's rows of concurrency pools, and the Recent feed's lines for the runs that
// start, queue, change step and end. Both read the runs contract's `pools` and each DAG's `active` runs, never a simulation.
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
}

/** The task a run id embeds (`deliver-agent-task-2787-…` is TASK-2787, a demo run's `…-demo-4` is DEMO-4), else the run id itself. */
const taskOf = (runId: string) => {
  const m = /(?:^|-)(task|demo)-(\d+)/i.exec(runId);
  return m ? `${m[1].toUpperCase()}-${m[2]}` : runId;
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
    const line = (dag: Dag, runId: string, what: string, tone?: "ok" | "failed") =>
      add.push({ key: `r${this.seq++}`, at, who: names.get(dag.name) ?? dag.name, what: "", where: `${what} · ${taskOf(runId)}`, tone, fresh: true, runId });
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
