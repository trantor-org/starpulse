import type { KanbanTask } from "./kanban";

/** One leaderboard row: a workable task and how long it has been workable. `width` is its bar, a percent of the longest age shown. */
export interface LeaderRow { id: string; title: string; seconds: number; width: number }
/** One open status: its label, how many of its tasks are workable, how many are held back and its longest-workable tasks. */
export interface LeaderGroup { status: string; label: string; workable: number; held: number; rows: LeaderRow[] }

/** The open statuses in the order the leaderboard draws them, each with the label the navigator shows. */
const STATUSES: [string, string][] = [["needs_attention", "Needs you"], ["in_progress", "Working"], ["review", "Review"], ["waiting", "Waiting"], ["ready", "Ready"]];
/** Tasks drawn per status. */
const PER_STATUS = 3;

/** An age as minutes under an hour, hours under a day, else days. */
export const age = (seconds: number): string =>
  seconds < 3600 ? `${Math.max(1, Math.floor(seconds / 60))}m` : seconds < 86400 ? `${Math.floor(seconds / 3600)}h` : `${Math.round(seconds / 86400)}d`;

const number = (id: string) => Number(/(\d+)$/.exec(id)?.[1] ?? 0);

/**
 * The workable tasks of each open status, longest since `workableSince` first, the longest three kept. A task that is not
 * workable never shows, only counts in its status's `held`; a status with no workable task is left out. Every bar is sized
 * against the longest age shown, so the groups compare with each other.
 */
export function leaderboard(tasks: KanbanTask[], now: number): LeaderGroup[] {
  const groups = STATUSES.map(([status, label]) => {
    const open = tasks.filter((t) => t.lane === status);
    const ranked = open.filter((t) => t.workableSince !== null)
      .map((t) => ({ id: t.id, title: t.title, seconds: Math.max(0, now - t.workableSince!), width: 0 }))
      .sort((a, b) => b.seconds - a.seconds || number(a.id) - number(b.id));
    return { status, label, workable: ranked.length, held: open.length - ranked.length, rows: ranked.slice(0, PER_STATUS) };
  }).filter((g) => g.rows.length);
  const longest = Math.max(1, ...groups.flatMap((g) => g.rows.map((r) => r.seconds)));
  return groups.map((g) => ({ ...g, rows: g.rows.map((r) => ({ ...r, width: Math.max(2, Math.round((r.seconds / longest) * 100)) })) }));
}
