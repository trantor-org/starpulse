// The Kanban view's moves: what a drag offers, the card that lands at once while the board writer is asked, and the refusal that
// returns it. The writer decides; the snapshot's verdicts only forecast it, so a late refusal still has to put the card back.
import { apiFetch } from "./demo";
import type { KanbanTask } from "./kanban";

/** The writer's answer to a move: done, or refused with its reason and the skill that satisfies it (empty when none). */
export type Reply = { ok: true } | { ok: false; reason: string; skill: string };
export type Post = (task: string, to: string) => Promise<Reply>;

/** A move the card shows as made, since `at` (epoch seconds): `saving` until the writer confirms, then held until the stream reports the lane. */
export interface Pending {
  from: string;
  to: string;
  saving: boolean;
  at: number;
}
export interface Refusal {
  from: string;
  to: string;
  reason: string;
  skill: string;
}
export interface MoveState {
  pending: Record<string, Pending>;
  refused: Record<string, Refusal>;
}

/** What dropping on a column does: the card's own column, an allowed move, one a declared guard refuses, or none the machine offers. */
export type Target = { kind: "here" | "ok" | "no" } | { kind: "guard"; reason: string; skill: string };

export const targets = (task: KanbanTask, columns: string[]): Record<string, Target> =>
  Object.fromEntries(
    columns.map((column): [string, Target] => {
      const verdict = task.moves[column];
      if (column === task.lane) return [column, { kind: "here" }];
      if (!verdict) return [column, { kind: "no" }];
      return [column, verdict.allowed ? { kind: "ok" } : { kind: "guard", reason: verdict.reason ?? "", skill: verdict.skill ?? "" }];
    }),
  );

const without = <T>(map: Record<string, T>, id: string) => Object.fromEntries(Object.entries(map).filter(([key]) => key !== id));

export class MoveStore {
  private state: MoveState = { pending: {}, refused: {} };
  private listeners = new Set<() => void>();
  constructor(private post: Post, private clock: () => number = () => Date.now() / 1000) {}

  get = () => this.state;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<MoveState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }

  /** Drop `task` on column `to`: a refusal on the card with no request when the verdict says so, else the card lands at once and the writer is asked. */
  async drop(task: KanbanTask, to: string): Promise<void> {
    const { id, lane: from } = task;
    if (to === from || this.state.pending[id]) return;
    const verdict = task.moves[to];
    if (!verdict || !verdict.allowed) {
      const refusal = { from, to, reason: verdict?.reason ?? `the board machine has no move from ${from} to ${to}`, skill: verdict?.skill ?? "" };
      this.set({ refused: { ...this.state.refused, [id]: refusal } });
      return;
    }
    const entry: Pending = { from, to, saving: true, at: this.clock() };
    this.set({ refused: without(this.state.refused, id), pending: { ...this.state.pending, [id]: entry } });
    const reply = await this.post(id, to);
    if (!this.state.pending[id]) return; // the stream already moved the card
    if (reply.ok) this.set({ pending: { ...this.state.pending, [id]: { ...entry, saving: false } } });
    else this.set({ pending: without(this.state.pending, id), refused: { ...this.state.refused, [id]: { from, to, reason: reply.reason, skill: reply.skill } } });
  }

  dismiss(id: string) {
    this.set({ refused: without(this.state.refused, id) });
  }

  /** The streamed board: a pending move or refusal ends once the card is no longer in the lane it was dropped from. */
  sync(cards: KanbanTask[]) {
    const lane = new Map(cards.map((c) => [c.id, c.lane]));
    const stale = (entry: { from: string }, id: string) => lane.has(id) && lane.get(id) !== entry.from;
    const pending = Object.fromEntries(Object.entries(this.state.pending).filter(([id, p]) => !stale(p, id)));
    const refused = Object.fromEntries(Object.entries(this.state.refused).filter(([id, r]) => !stale(r, id)));
    if (Object.keys(pending).length !== Object.keys(this.state.pending).length || Object.keys(refused).length !== Object.keys(this.state.refused).length) {
      this.set({ pending, refused });
    }
  }
}

/** The cards with each pending move already made: in the target column, newest there, so it lands at the top. */
export const place = (tasks: KanbanTask[], state: MoveState): KanbanTask[] =>
  tasks.map((t) => {
    const p = state.pending[t.id];
    return p ? { ...t, lane: p.to, live: { machine: "board", state: p.to, at: p.at } } : t;
  });

/** POST the move to the server, which runs the guarded board writer. */
export async function postMove(task: string, to: string, fetcher: typeof apiFetch = apiFetch): Promise<Reply> {
  let response: Response;
  try {
    response = await fetcher("/api/move", { method: "POST", body: JSON.stringify({ task, to }) });
  } catch {
    return { ok: false, reason: "the move did not reach the server", skill: "" };
  }
  if (response.ok) return { ok: true };
  const body: { error?: string; skill?: string } | null = await response.json().catch(() => null);
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}`, skill: body?.skill ?? "" };
}

/** `text` split at its `backtick` pairs: the guard's wording quotes the criterion it needs. */
export const codeParts = (text: string): { code: boolean; text: string }[] =>
  text.split(/`([^`]*)`/).map((part, i) => ({ code: i % 2 === 1, text: part })).filter((p) => p.text);
