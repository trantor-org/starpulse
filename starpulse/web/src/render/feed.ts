import type { Dag, FlowSnapshot } from "../api";
import type { RunLine } from "../features/fanout/fanoutModel";
import type { FeedLine } from "./hud";
import type { Move } from "./sky";

export const finished = (iso: string) => (iso ? Date.parse(iso) / 1000 : NaN);

/** A session's per-call moves: one a tool or skill use, too many to read in the feed. */
const CHATTER = new Set(["TOOL_USED", "SKILL_USED"]);
/** A session id (a UUID), which the feed writes as its first block. */
const SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-/i;

/** The Board task each session holds, by session id: what a session's feed line is named for. */
export const heldTasks = (board: FlowSnapshot | undefined) => new Map((board?.agents ?? []).flatMap((a) => (a.assignee ? [[a.assignee, a.id] as const] : [])));

/**
 * The Recent feed's newest 40 lines at `now`: each move but a session's tool and skill uses, each DAG run's line, and a DAG's own line for a run
 * no run line ended. A session's line is named for the task it holds in `held`, else for its id's first block.
 */
export function feedOf(moves: Move[], dags: Dag[], runs: RunLine[], now: number, held = new Map<string, string>()): Omit<FeedLine, "time">[] {
  const ev: Omit<FeedLine, "time">[] = moves.filter((e) => e.at <= now && !CHATTER.has(e.event)).map((e) => {
    const task = (e.task && held.get(e.task)) ?? e.task ?? undefined;
    const who = task && SESSION_ID.test(task) ? task.slice(0, 8) : task ?? "";
    return { key: `m${e.machine}:${e.task ?? ""}:${e.event}:${e.at}`, at: e.at, who, what: e.event.toLowerCase(), where: e.machine, task };
  });
  // a run line already says how its run ended, so the DAG's own line for that run is left out
  const told = new Set(runs.filter((l) => l.tone).map((l) => l.runId));
  for (const d of dags) {
    const f = finished(d.finishedAt);
    if (f <= now && !told.has(d.runId)) ev.push({ key: `d${d.name}`, at: f, who: d.name, what: "", where: d.status, dag: d.name });
  }
  ev.push(...runs);
  return ev.sort((a, b) => b.at - a.at).slice(0, 40);
}
