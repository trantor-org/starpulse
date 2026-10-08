// The Start Criteria the public preview gives a Waiting task: met, unmet and a time() wait, or one whose evaluator fails.
import type { StartCriterion } from "./taskView";

const iso = (sec: number) => new Date(sec * 1000).toISOString();

/** A Waiting demo task's criteria: a measurement met, one unmet and a time() wait, or with `failing` one the evaluator could not read. */
export function demoCriteria(now: number, failing: boolean): StartCriterion[] {
  const checked = iso(now - 180);
  const rows: StartCriterion = { id: "rows-50", kind: "sql", expr: "select count(*) from runs", cmp: "at_least", want: 50, status: "met", observed: 61, error: null, checked };
  if (failing) {
    return [rows, { id: "p95-under-1s", kind: "prom", expr: "histogram_quantile(0.95, rate(dashboard_latency_seconds_bucket[1h]))", cmp: "at_most", want: 1, status: "error", observed: null, checked: null,
      error: "bin/backlog_task.py criteria: exit 1: prometheus query failed: connection refused" }];
  }
  return [
    rows,
    { id: "pin-moved", kind: "file_changed_since", expr: "starpulse", cmp: "since", want: "2026-10-05", status: "unmet", observed: 0, error: null, checked },
    { id: "window-24h", kind: "prom", expr: "time()", cmp: "at_least", want: now + 3600 * 5, status: "unmet", observed: now, error: null, checked },
  ];
}

const queryKey = (kind: string) => (kind === "sql" ? "query" : kind === "prom" ? "expr" : "path");

/** The description's `## Start Criteria` section for `criteria`, as the board file writes it. */
export const criteriaBlock = (criteria: StartCriterion[]): string =>
  `## Start Criteria\n\n\`\`\`yaml\nstart_criteria:\n${criteria.map((c) => `- id: ${c.id}\n  kind: ${c.kind}\n  ${queryKey(c.kind)}: ${c.expr}\n  ${c.cmp}: ${c.want}`).join("\n")}\n\`\`\``;
