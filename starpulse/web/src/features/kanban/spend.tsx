import { useEffect, useState } from "react";
import { apiFetch } from "../../api/apiFetch";
import { taskQuery } from "../../api/taskQuery";
import type { SpendPhase } from "../../api";

/** How long the page keeps a task's spend answer: the report folds a week of model requests, so the drawer asks once a minute at most per task. */
const TTL_MS = 60_000;
/** A failed read is asked again after this, so a blip does not read as a minute of nothing. */
const FAILED_TTL_MS = 5_000;

/** Every field of a `SpendPhase` the rail draws or totals. */
const SPEND_FIELDS =
  "task phase kind size steps side_steps input output cache_read cache_write wte peak_context compactions models profile first_at last_at task_wte norm_wte above_norm phase_norm_wte norm_profile no_norm_reason phase_above_norm";

const cached = new Map<string, { at: number; ttl: number; answer: Promise<SpendPhase[] | null> }>();

/** A read the server has not answered by then is abandoned: a stalled server would otherwise leave the rail on "Reading spend…" for good. */
const READ_TIMEOUT_MS = 15_000;

/** One task's phases over the last week; `null` when the read is refused, unanswered after `READ_TIMEOUT_MS` (the request is aborted) or answers something else, kept for a few seconds only. */
export function fetchSpend(task: string, fetcher: typeof apiFetch = apiFetch, now: number = Date.now()): Promise<SpendPhase[] | null> {
  const kept = cached.get(task);
  if (kept && now - kept.at < kept.ttl) return kept.answer;
  const answer = (async (): Promise<SpendPhase[] | null> => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timedOut = new Promise<null>((resolve) => { timer = setTimeout(() => { abort.abort(); resolve(null); }, READ_TIMEOUT_MS); });
    try {
      const found = await Promise.race([taskQuery<{ spend: SpendPhase[] | null }>(task, `spend { ${SPEND_FIELDS} }`, fetcher, abort.signal), timedOut]);
      return Array.isArray(found?.spend) ? found.spend : null;
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  })();
  const entry = { at: now, ttl: TTL_MS, answer };
  cached.set(task, entry);
  void answer.then((rows) => { if (rows === null) entry.ttl = FAILED_TTL_MS; });
  return answer;
}

/** Forget the cached answers, so the next read asks again. */
export const forgetSpend = (): void => { cached.clear(); };

/** Weighted tokens as `812`, `4.2K`, `1.3M`. */
export function compactWte(wte: number): string {
  if (wte >= 1e6) return `${(wte / 1e6).toFixed(1)}M`;
  if (wte >= 1e3) return `${(wte / 1e3).toFixed(wte >= 1e5 ? 0 : 1)}K`;
  return String(Math.round(wte));
}

const PHASES = ["claim", "implement", "qa", "deliver", "review_fix"];
const PHASE_NAME: Record<string, string> = { claim: "Claim", implement: "Implement", qa: "QA", deliver: "Deliver", review_fix: "Review fix" };

/** The task's phases in lifecycle order. */
export const phasesOf = (rows: SpendPhase[], task: string): SpendPhase[] =>
  rows.filter((r) => r.task === task).sort((a, b) => PHASES.indexOf(a.phase) - PHASES.indexOf(b.phase));

/** `sonnet-5-5` from `claude-sonnet-5-5`: the vendor prefix says nothing in a narrow rail. */
const shortModel = (model: string): string => model.replace(/^claude-/, "");

/** The task drawer's Spend section body: the task's weighted tokens by phase, flagged when far above its kind and size norm. */
export function SpendRows({ rows }: { rows: SpendPhase[] }) {
  if (rows.length === 0) return <span className="none">No spend recorded in the last 7 days</span>;
  const total = rows[0].task_wte;
  const norm = rows[0].norm_wte;
  const top = Math.max(...rows.map((r) => r.wte), 1);
  return <div className="spend">
    <div className="spend-total">
      <span className="big" title="Weighted token equivalents: an uncached input token is 1, a cache write 1.25, a cache read 0.1, an output token 5">{compactWte(total)} WTE</span>
      {rows[0].above_norm && norm != null && <span className="spend-flag" title={`Median for ${rows[0].kind ?? "?"} size ${rows[0].size ?? "?"}: ${compactWte(norm)} WTE`}>{(total / norm).toFixed(1)}× norm ({compactWte(norm)})</span>}
      {!rows[0].above_norm && norm != null && <span className="k">norm {compactWte(norm)}</span>}
      {norm == null && <span className="k">no norm: {rows.find((r) => r.no_norm_reason)?.no_norm_reason}</span>}
    </div>
    {rows.map((r) => <div className="spend-row" key={r.phase} data-phase={r.phase}>
      <span className="ph">{PHASE_NAME[r.phase] ?? r.phase}</span>
      <span className="bar"><i style={{ width: `${Math.max((r.wte / top) * 100, 2)}%` }} /></span>
      <span className="v">{compactWte(r.wte)}</span>
      <span className="sub">{r.steps} step{r.steps === 1 ? "" : "s"}{r.compactions > 0 && ` · ${r.compactions} compaction${r.compactions === 1 ? "" : "s"}`}{r.models.length > 0 && ` · ${r.models.map(shortModel).join(", ")}`}</span>
    </div>)}
  </div>;
}

/** The task's spend, read once per minute per task; "Reading spend…" until the read answers, "Spend unavailable" when it fails, read again after `FAILED_TTL_MS` until it answers. */
export function SpendRail({ task }: { task: string }) {
  const [rows, setRows] = useState<SpendPhase[] | null | "unavailable">(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    let retry: ReturnType<typeof setTimeout> | undefined;
    void fetchSpend(task).then((all) => {
      if (!live) return;
      setRows(all === null ? "unavailable" : phasesOf(all, task));
      if (all === null) retry = setTimeout(() => setAttempt((n) => n + 1), FAILED_TTL_MS);
    });
    return () => { live = false; clearTimeout(retry); };
  }, [task, attempt]);
  if (rows === null) return <span className="none" role="status">Reading spend…</span>;
  return rows === "unavailable" ? <span className="none" role="status">Spend unavailable</span> : <SpendRows rows={rows} />;
}
