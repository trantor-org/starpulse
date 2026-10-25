// Hover and click targets on the Suns board: which sun, round pill or flow line sits under the pointer, the details a hover shows and the
// backtrace of a machine's moves. Pure, so the canvas only paints what these return.
import type { Flow, SunsBoard } from "./sunsBoard";
import type { MachineEvent } from "./sunsReplay";

export type Hit =
  | { kind: "sun"; id: string }
  | { kind: "pill"; id: string; round: number }
  | { kind: "entry" | "exit"; id: string };

export interface Details {
  title: string;
  lines: string[];
  /** The machine's latest moves, newest first. */
  trace: string[];
}

const SUN_SLACK = 4, PILL_HALF_W = 15, PILL_HALF_H = 9, LINE_HALF = 6, TRACE = 5;

/** What each exit means, so the board needs no legend. */
const EXIT_MEANS: Record<string, string> = { "Needs Attention": "the task waits on a person", Done: "the work is done" };

const onFlow = (f: Flow, x: number, y: number) => {
  const { x0, x1, y: ly } = f.line, l = f.label;
  const onLine = x >= x0 && x <= x1 && Math.abs(y - ly) <= LINE_HALF;
  const onLabel = x >= l.x && x <= l.x + l.w && y >= l.y - l.h && y <= l.y;
  return onLine || onLabel;
};

export function hitAt(b: SunsBoard, x: number, y: number): Hit | null {
  for (const r of b.rows) {
    const i = r.pills.findIndex((p) => Math.abs(x - p.x) <= PILL_HALF_W && Math.abs(y - p.y) <= PILL_HALF_H);
    if (i >= 0) return { kind: "pill", id: r.id, round: i + 1 };
  }
  const sun = b.suns.find((s) => Math.hypot(x - s.x, y - s.y) <= s.r + SUN_SLACK);
  if (sun) return { kind: "sun", id: sun.id };
  const exit = b.exits.find((f) => onFlow(f, x, y));
  if (exit) return { kind: "exit", id: exit.label.text };
  const entry = b.entries.find((f) => onFlow(f, x, y));
  return entry ? { kind: "entry", id: entry.label.text } : null;
}

/** A machine's moves up to t, newest first. */
export function backtrace(events: MachineEvent[], machine: string, t: number, limit = TRACE): MachineEvent[] {
  return events
    .filter((e) => e.machine === machine && e.at <= t)
    .sort((a, b) => b.at - a.at)
    .slice(0, limit);
}

export function detailsOf(b: SunsBoard, hit: Hit, events: MachineEvent[]): Details {
  if (hit.kind === "entry") return { title: hit.id, lines: ["enters Build"], trace: [] };
  if (hit.kind === "exit") return { title: hit.id, lines: ["leaves Deliver", EXIT_MEANS[hit.id] ?? ""].filter(Boolean), trace: [] };
  const row = b.rows.find((r) => r.id === hit.id)!;
  const round = hit.kind === "pill" ? hit.round : row.pills.findIndex((p) => p.current) + 1;
  const trace = backtrace(events, row.id, Infinity).map((e) => `${e.from} → ${e.to}`);
  return { title: row.name, lines: [row.state, `round ${round} of ${row.pills.length}`], trace };
}
