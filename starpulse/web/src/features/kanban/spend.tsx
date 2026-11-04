import { useEffect, useState } from "react";
import { apiFetch } from "../../api/apiFetch";
import type { Spend, SpendPhase } from "../../api";

/** How long the page keeps a spend answer: the report folds a week of model requests, so the drawer asks once a minute at most. */
const TTL_MS = 60_000;
/** A failed read is asked again after this, so a blip does not read as a minute of nothing. */
const FAILED_TTL_MS = 5_000;

let cached: { at: number; ttl: number; answer: Promise<SpendPhase[] | null> } | null = null;

/** Every task's phases over the last week; `null` when the read is refused, times out or answers something else, kept for a few seconds only. */
export function fetchSpend(fetcher: typeof apiFetch = apiFetch, now: number = Date.now()): Promise<SpendPhase[] | null> {
  if (cached && now - cached.at < cached.ttl) return cached.answer;
  const answer = (async (): Promise<SpendPhase[] | null> => {
    try {
      const response = await fetcher("/api/analytics/spend");
      if (!response.ok) return null;
      const body: Partial<Spend> | null = await response.json().catch(() => null);
      return Array.isArray(body?.spend) ? body.spend : null;
    } catch {
      return null;
    }
  })();
  const entry = { at: now, ttl: TTL_MS, answer };
  cached = entry;
  void answer.then((rows) => { if (rows === null) entry.ttl = FAILED_TTL_MS; });
  return answer;
}

/** Forget the cached answer, so the next read asks again. */
export const forgetSpend = (): void => { cached = null; };

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
    </div>
    {rows.map((r) => <div className="spend-row" key={r.phase} data-phase={r.phase}>
      <span className="ph">{PHASE_NAME[r.phase] ?? r.phase}</span>
      <span className="bar"><i style={{ width: `${Math.max((r.wte / top) * 100, 2)}%` }} /></span>
      <span className="v">{compactWte(r.wte)}</span>
      <span className="sub">{r.steps} step{r.steps === 1 ? "" : "s"}{r.compactions > 0 && ` · ${r.compactions} compaction${r.compactions === 1 ? "" : "s"}`}{r.models.length > 0 && ` · ${r.models.map(shortModel).join(", ")}`}</span>
    </div>)}
  </div>;
}

/** The task's spend, read once per minute for the whole board; "Reading spend…" until the read answers, "Spend unavailable" when it fails. */
export function SpendRail({ task }: { task: string }) {
  const [rows, setRows] = useState<SpendPhase[] | null | "unavailable">(null);
  useEffect(() => {
    let live = true;
    void fetchSpend().then((all) => { if (live) setRows(all === null ? "unavailable" : phasesOf(all, task)); });
    return () => { live = false; };
  }, [task]);
  if (rows === null) return <span className="none" role="status">Reading spend…</span>;
  return rows === "unavailable" ? <span className="none" role="status">Spend unavailable</span> : <SpendRows rows={rows} />;
}
