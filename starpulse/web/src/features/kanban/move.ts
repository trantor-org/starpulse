// The Kanban view's moves: what a drag offers, the card that lands at once while the board writer is asked, and the refusal that
// returns it. The writer decides; the snapshot's verdicts only forecast it, so a late refusal still has to put the card back.
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";
import type { Move, RuleBreak, TaskMoves } from "../../api";
import type { KanbanTask } from "./kanbanModel";

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
/** An operator move that breaks lane rules, waiting on Confirm: `busy` while the write runs, `refused` the writer's reason once it turned it down. */
export interface Overriding {
  task: KanbanTask;
  to: string;
  warnings: RuleBreak[];
  busy: boolean;
  refused: string | null;
}
export interface MoveState {
  pending: Record<string, Pending>;
  refused: Record<string, Refusal>;
  asking: Overriding | null;
}

/** What dropping on a column does: the card's own column, an allowed move, one a declared guard refuses, or none the machine offers. */
export type Target = { kind: "here" | "ok" | "no" } | { kind: "guard"; reason: string; skill: string };

/** The verdict as the page's operator meets it: the snapshot's own, or the one kept for the operator when a guard treats it apart, or a refusal naming who writes the move when the board machine declares writers and the operator is none of them. */
export const asOperator = (move: Move): Move => {
  const own = move.actors?.[PAGE_ACTOR];
  const verdict = own ? { ...move, ...own } : move;
  const writers = verdict.writers ?? [];
  if (!writers.length || writers.includes(PAGE_ACTOR)) return verdict;
  return { ...verdict, allowed: false, reason: `only the ${writers.join(" or ")} may make this move, not the ${PAGE_ACTOR}` };
};

/** The rules `to` would break if the page's operator moved `task` there, which the operator may still confirm; empty when the move breaks none or is refused. */
export const warnsOf = (task: KanbanTask, to: string): RuleBreak[] => {
  const verdict = task.moves[to] && asOperator(task.moves[to]);
  return verdict?.allowed ? verdict.warnings ?? [] : [];
};

export const targets = (task: KanbanTask, columns: string[]): Record<string, Target> =>
  Object.fromEntries(
    columns.map((column): [string, Target] => {
      const verdict = task.moves[column] && asOperator(task.moves[column]);
      if (column === task.lane) return [column, { kind: "here" }];
      if (!verdict) return [column, { kind: "no" }];
      return [column, verdict.allowed ? { kind: "ok" } : { kind: "guard", reason: verdict.reason ?? "", skill: verdict.skill ?? "" }];
    }),
  );

const without = <T>(map: Record<string, T>, id: string) => Object.fromEntries(Object.entries(map).filter(([key]) => key !== id));

/** The moves the board's guards judge for one task now, or null when they could not be read. */
export type Standing = (id: string) => Promise<KanbanTask["moves"] | null>;

export class MoveStore {
  private state: MoveState = { pending: {}, refused: {}, asking: null };
  private listeners = new Set<() => void>();
  constructor(private post: Post, private clock: () => number = () => Date.now() / 1000, private standing?: Standing) {}

  get = () => this.state;
  /** The moves the board's guards judge for `id` now, null when the store has no such read or it failed. */
  guarded = (id: string): Promise<KanbanTask["moves"] | null> => (this.standing ? this.standing(id).catch(() => null) : Promise.resolve(null));
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<MoveState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }

  /** Drop `task` on column `to`: a refusal on the card with no request when the verdict says so, a question when the move breaks rules the operator may override, else the card lands at once and the writer is asked. */
  async drop(streamed: KanbanTask, to: string): Promise<void> {
    const { id, lane: from } = streamed;
    if (to === from || this.state.pending[id] || this.state.asking) return;
    let task = streamed;
    if (this.standing) {
      task = await this.judged(streamed);
      if (this.state.pending[id] || this.state.asking) return; // another drop landed or asked while the guards were read
    }
    const verdict = task.moves[to] && asOperator(task.moves[to]);
    if (!verdict || !verdict.allowed) {
      const refusal = { from, to, reason: verdict?.reason ?? `the board machine has no move from ${from} to ${to}`, skill: verdict?.skill ?? "" };
      this.set({ refused: { ...this.state.refused, [id]: refusal } });
      return;
    }
    const warnings = warnsOf(task, to);
    if (warnings.length) {
      this.set({ refused: without(this.state.refused, id), asking: { task, to, warnings: [...warnings], busy: false, refused: null } });
      return;
    }
    await this.land(task, to, false);
  }

  /** The card with the moves the board's guards judge now: the streamed ones leave the guards unjudged, and a failed read leaves the card as it was. */
  private async judged(task: KanbanTask): Promise<KanbanTask> {
    const fresh = await this.guarded(task.id);
    return fresh ? judgedBy(task, fresh) : task;
  }

  /** The operator's Confirm: the move the question held is written as an ordinary move. */
  async confirm(): Promise<void> {
    const asking = this.state.asking;
    if (!asking || asking.busy || asking.refused) return;
    this.set({ asking: { ...asking, busy: true } });
    await this.land(asking.task, asking.to, true);
  }

  /** The operator's Cancel: nothing is written, and none while the write runs. */
  cancel() {
    if (this.state.asking && !this.state.asking.busy) this.set({ asking: null });
  }

  /** The card lands in `to` at once, `saving` until the writer answers; a refusal returns it, onto the question when `asked`, else onto the card. */
  private async land(task: KanbanTask, to: string, asked: boolean): Promise<void> {
    const { id, lane: from } = task;
    const entry: Pending = { from, to, saving: true, at: this.clock() };
    this.set({ refused: without(this.state.refused, id), pending: { ...this.state.pending, [id]: entry } });
    const reply = await this.post(id, to);
    const closed = asked ? null : this.state.asking; // only the confirmed move closes the question; another card's warning stays
    if (!this.state.pending[id]) return this.set({ asking: closed }); // the stream already moved the card
    if (reply.ok) this.set({ asking: closed, pending: { ...this.state.pending, [id]: { ...entry, saving: false } } });
    else if (asked) this.set({ pending: without(this.state.pending, id), asking: { ...this.state.asking!, busy: false, refused: reply.reason } });
    else this.set({ pending: without(this.state.pending, id), refused: { ...this.state.refused, [id]: { from, to, reason: reply.reason, skill: reply.skill } } });
  }

  dismiss(id: string) {
    this.set({ refused: without(this.state.refused, id) });
  }

  /** The streamed board: a pending move or refusal ends once the card is no longer in the lane it was dropped from. */
  sync(cards: KanbanTask[]) {
    const lane = new Map(cards.map((c) => [c.id, c.lane]));
    const asking = this.state.asking;
    if (asking && !asking.busy && lane.has(asking.task.id) && lane.get(asking.task.id) !== asking.task.lane) this.set({ asking: null });
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
    response = await fetcher("/api/move", { method: "POST", body: JSON.stringify({ task, to, actor: PAGE_ACTOR }) });
  } catch {
    return { ok: false, reason: "the move did not reach the server", skill: "" };
  }
  if (response.ok) return { ok: true };
  const body: { error?: string; skill?: string } | null = await response.json().catch(() => null);
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}`, skill: body?.skill ?? "" };
}

/** `task` with the guarded `moves` read over its streamed, unjudged ones. */
export const judgedBy = (task: KanbanTask, moves: KanbanTask["moves"]): KanbanTask => ({ ...task, moves: { ...task.moves, ...moves } });

/** GET the guarded verdict on each column for `task`; the streamed snapshot leaves them unjudged. */
export async function fetchStanding(task: string, fetcher: typeof apiFetch = apiFetch): Promise<KanbanTask["moves"] | null> {
  const response = await fetcher(`/api/moves/${encodeURIComponent(task)}`);
  if (!response.ok) return null;
  const body: TaskMoves | null = await response.json().catch(() => null);
  return body?.moves ?? null;
}

/** `text` split at its `backtick` pairs: the guard's wording quotes the criterion it needs. */
export const codeParts = (text: string): { code: boolean; text: string }[] =>
  text.split(/`([^`]*)`/).map((part, i) => ({ code: i % 2 === 1, text: part })).filter((p) => p.text);
