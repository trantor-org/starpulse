// The Ledger's forced rerun: the one request, whose refusal comes back as a value for the merge panel to show.
import { apiFetch } from "./demo";
import type { Dag } from "./api";

export type RerunResult = { ok: true; runId: string } | { ok: false; reason: string };

/** Start the run-safe DAG `<instance>/<workflow>` again, forced, on the commit of its newest unresolved failure. */
export async function postRerun(dag: string, fetcher: typeof apiFetch = apiFetch): Promise<RerunResult> {
  let response: Response;
  try {
    response = await fetcher(`/api/runs/${dag}/rerun`, { method: "POST" });
  } catch {
    return { ok: false, reason: `The server could not be reached; ${dag} was not rerun.` };
  }
  const body = await response.json().catch(() => null) as { runId?: string; error?: string } | null;
  if (response.ok && body?.runId) return { ok: true, runId: body.runId };
  return { ok: false, reason: body?.error ?? `The server answered ${response.status}; ${dag} was not rerun.` };
}

export interface RerunState {
  /** The DAGs whose rerun is being asked for. */
  busy: ReadonlySet<string>;
  /** Why the server refused a DAG's rerun, until the next try. */
  refused: Readonly<Record<string, string>>;
  /** The forced run each DAG last started, and when (epoch seconds). */
  started: Readonly<Record<string, { runId: string; at: number }>>;
}

/** The Ledger's forced reruns: one request at a time for a DAG, its refusal held for the merge panel to show, the run it started held to word the band. */
export class RerunStore {
  state: RerunState = { busy: new Set(), refused: {}, started: {} };

  constructor(private post: (dag: string) => Promise<RerunResult> = postRerun, private onChange: () => void = () => {}) {}

  async run(dag: string, now: number): Promise<void> {
    if (this.state.busy.has(dag)) return;
    const refused = { ...this.state.refused };
    delete refused[dag];
    this.set({ busy: new Set([...this.state.busy, dag]), refused });
    const result = await this.post(dag);
    const busy = new Set(this.state.busy);
    busy.delete(dag);
    this.set(result.ok ? { busy, started: { ...this.state.started, [dag]: { runId: result.runId, at: now } } } : { busy, refused: { ...this.state.refused, [dag]: result.reason } });
  }

  private set(next: Partial<RerunState>) {
    this.state = { ...this.state, ...next };
    this.onChange();
  }
}

/** The band's words for a forced rerun still running (`↻ forced rerun of a/b running · 12 s`); none once it has finished or before the snapshot shows it. */
export function rerunLine(started: RerunState["started"], dags: readonly Dag[], now: number): string | undefined {
  for (const [dag, s] of Object.entries(started)) {
    if (dags.find((d) => d.name === dag)?.active?.some((r) => r.runId === s.runId)) return `↻ forced rerun of ${dag} running · ${Math.round(now - s.at)} s`;
  }
  return undefined;
}
