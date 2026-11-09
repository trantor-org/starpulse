// The per-phase spend the public preview gives its Board tasks, so the task drawer's Spend section draws every state.
import type { Snapshot, SpendPhase } from "../api";

const MODELS = ["claude-sonnet-5-5"];

const phase = (task: string, name: string, steps: number, wte: number, over: Partial<SpendPhase> = {}): SpendPhase => ({
  task, phase: name, steps, side_steps: 0, input: 0, output: 0, cache_read: 0, cache_write: 0, wte, peak_context: 60_000,
  compactions: 0, models: MODELS, first_at: 0, last_at: 0, kind: "execute", size: 3, task_wte: 0, norm_wte: 900_000, above_norm: false, ...over,
});

/** Board task i of the demo: none for every fourth, one phase for the next, a full lifecycle at the norm after, and the fifth far above it. */
function demoRows(task: string, i: number): SpendPhase[] {
  if (i % 4 === 0) return [];
  const rows = i % 4 === 1
    ? [phase(task, "implement", 12, 140_000)]
    : i % 4 === 2
      ? [phase(task, "claim", 6, 90_000), phase(task, "implement", 140, 620_000, { compactions: 1, models: ["claude-opus-5-5", "claude-sonnet-5-5"] }), phase(task, "qa", 40, 210_000), phase(task, "deliver", 25, 80_000)]
      : [phase(task, "claim", 14, 410_000), phase(task, "implement", 380, 3_900_000, { compactions: 4 }), phase(task, "review_fix", 90, 1_100_000)];
  const total = rows.reduce((sum, r) => sum + r.wte, 0);
  return rows.map((r) => ({ ...r, task_wte: total, above_norm: total > 3 * (r.norm_wte ?? Infinity) }));
}

/** `GET /api/analytics/spend` for the demo's Board tasks. */
export function demoSpend(snapshot: Snapshot) {
  const tasks = snapshot.flows.find((f) => f.name === "board")?.agents.map((a) => a.id) ?? [];
  return { now: snapshot.now, window_s: 7 * 86400, spend: tasks.flatMap(demoRows) };
}
