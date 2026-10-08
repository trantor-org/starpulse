// Starting a session from the Kanban view: the question a move to In progress asks, the profile it picks, and the card that waits
// in In progress for its agent's claim. The session-start service opens the session; the agent's own claim moves the task, and the
// board writer's refusal of that claim (a `claim` delta) returns the card to its lane.
import { apiFetch } from "../../api/apiFetch";
import type { KanbanTask } from "./kanban";
import type { MoveStore } from "./move";

/** A harness `GET /api/harnesses` names: its tiers' models and efforts, and whether it can run a session (and why not). */
export interface Harness {
  name: string;
  label: string;
  sessions: boolean;
  reason: string;
  tiers: Record<string, { model: string; efforts: string[] }>;
}
export interface Harnesses {
  tiers: string[];
  harnesses: Harness[];
}
/** The question's choice; `effort` is empty for a tier that takes none. */
export interface Pick {
  harness: string;
  tier: string;
  effort: string;
}
/** The server's answer to a start: the session and when the start began (epoch seconds, the server's clock), or why it failed. */
export type StartReply = { ok: true; url: string; at: number } | { ok: false; reason: string };
export type PostStart = (task: string, assignee: string) => Promise<StartReply>;
/** Each task's latest refused claim, as the snapshot and `claim` deltas carry it. */
export type Claims = Record<string, { reason: string; at: number }>;

/** Where the question was asked from: a dropped card, the task modal's Start session button, or the card's ▶. */
export type Via = "drop" | "modal" | "play";
export interface Asking {
  task: KanbanTask;
  via: Via;
  pick: Pick;
}
/** A started card held in In progress: `starting` until the service answers, then `waiting` for the agent's claim. */
export interface Claiming {
  from: string;
  phase: "starting" | "waiting";
  url: string;
  at: number | null;
}
/** A start that failed, or a claim the writer refused (`refused`, with the session still open at `url`); the card is back in `from`. */
export interface Failed {
  from: string;
  reason: string;
  url: string;
  refused: boolean;
}
export interface StartState {
  /** The harnesses the question offers; none until the server names them. */
  harnesses: Harnesses;
  asking: Asking | null;
  claiming: Record<string, Claiming>;
  failed: Record<string, Failed>;
}

const STARTABLE = new Set(["ready", "waiting", "needs_attention"]);
const ACTIVE = "in_progress";
const DEFAULT = { tier: "standard", effort: "high" };
const PROFILE = /^@agent-([a-z]+)(?:-([a-z]+))?$/;

/** A task in a lane a session starts from; its ▶ is disabled while a guard refuses the move to In progress. */
export const startLane = (task: KanbanTask) => STARTABLE.has(task.lane);
/** A task a session can start: in a lane a session starts from, with the move to In progress allowed. */
export const startable = (task: KanbanTask) => startLane(task) && task.moves[ACTIVE]?.allowed === true;
/** Whether dropping `task` on column `to` asks how it starts rather than moving it. */
export const dropAsks = (task: KanbanTask, to: string) => to === ACTIVE && startable(task);

const harnessOf = (name: string, h: Harnesses) => h.harnesses.find((x) => x.name === name);

/** `pick` with `change` applied: an effort the tier does not take is dropped, and one is restored (High first) for a tier that takes one. */
export function choose(pick: Pick, h: Harnesses, change: Partial<Pick>): Pick {
  const next = { ...pick, ...change };
  const efforts = harnessOf(next.harness, h)?.tiers[next.tier]?.efforts ?? [];
  if (efforts.length === 0) return { ...next, effort: "" };
  if (efforts.includes(next.effort)) return next;
  return { ...next, effort: efforts.includes(DEFAULT.effort) ? DEFAULT.effort : efforts[efforts.length - 1] };
}

/** The question's starting pick: the task's assignee when it names a tier the harness has, else `@agent-standard-high`. */
export function defaultPick(assignee: string, h: Harnesses): Pick {
  const harness = (h.harnesses.find((x) => x.sessions) ?? h.harnesses[0])?.name ?? "";
  const [, tier, effort = ""] = PROFILE.exec(assignee) ?? [];
  const tiers = harnessOf(harness, h)?.tiers ?? {};
  if (tier && tiers[tier] && (tiers[tier].efforts.length ? tiers[tier].efforts.includes(effort) : !effort)) return { harness, tier, effort };
  return choose({ harness, ...DEFAULT }, h, {});
}

/** The assignee a pick saves: `@agent-<tier>-<effort>`, or `@agent-<tier>` for a tier with no effort. */
export const profileOf = (pick: Pick) => `@agent-${pick.tier}${pick.effort ? `-${pick.effort}` : ""}`;

/** The line under the pick: the model, its effort and the harness. */
export function runsOn(pick: Pick, h: Harnesses): string {
  const harness = harnessOf(pick.harness, h);
  const model = harness?.tiers[pick.tier]?.model ?? pick.tier;
  return `runs ${model}${pick.effort ? ` at ${pick.effort} effort` : ""} on ${harness?.label ?? pick.harness}`;
}

/** A card waiting for its claim stays put: the session is already working it. */
export const canDrag = (id: string, state: StartState) => !state.claiming[id];

/** The cards with each started one already in In progress. */
export const placeClaims = (tasks: KanbanTask[], state: StartState): KanbanTask[] =>
  tasks.map((t) => (state.claiming[t.id] ? { ...t, lane: ACTIVE } : t));

const without = <T>(map: Record<string, T>, id: string) => Object.fromEntries(Object.entries(map).filter(([key]) => key !== id));

export const NO_HARNESSES: Harnesses = { tiers: [], harnesses: [] };

export class StartStore {
  private state: StartState;
  private claims: Claims = {};
  private listeners = new Set<() => void>();
  constructor(private post: PostStart, private moves: MoveStore, harnesses: Harnesses = NO_HARNESSES) {
    this.state = { harnesses, asking: null, claiming: {}, failed: {} };
  }

  get = () => this.state;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<StartState>) {
    this.state = { ...this.state, ...patch };
    for (const fn of this.listeners) fn();
  }

  /** The harnesses `GET /api/harnesses` named, once they arrive. */
  load(harnesses: Harnesses) {
    this.set({ harnesses });
  }

  /** Ask how `task` starts; nothing for a task no session can start or one already waiting for its claim. */
  ask(task: KanbanTask, via: Via) {
    if (!startable(task) || this.state.claiming[task.id]) return;
    this.set({ asking: { task, via, pick: defaultPick(task.assignee, this.state.harnesses) } });
  }

  pick(change: Partial<Pick>) {
    const asking = this.state.asking;
    if (asking) this.set({ asking: { ...asking, pick: choose(asking.pick, this.state.harnesses, change) } });
  }

  /** Whether the pick's harness can run a session: none can when the server named no harness. */
  canStart(): boolean {
    const asking = this.state.asking;
    return !!asking && harnessOf(asking.pick.harness, this.state.harnesses)?.sessions === true;
  }

  /** The question's keys: 1 starts a session, 2 works it manually, Escape returns the card. True when the key answered the question. */
  key(key: string): boolean {
    const asking = this.state.asking;
    if (!asking) return false;
    if (key === "1") {
      if (!this.canStart()) return false;
      void this.start();
    } else if (key === "2") this.manual();
    else if (key === "Escape") this.cancel();
    else return false;
    return true;
  }

  cancel() {
    this.set({ asking: null });
  }

  /** Work it manually: an ordinary writer move, no session. */
  manual() {
    const asking = this.state.asking;
    if (!asking) return;
    this.set({ asking: null });
    void this.moves.drop(asking.task, ACTIVE);
  }

  /** Start a session on the pick: the card goes to In progress at once and waits there for the agent's claim. */
  async start(): Promise<void> {
    const asking = this.state.asking;
    if (!asking) return;
    const { id, lane: from } = asking.task;
    this.set({ asking: null, failed: without(this.state.failed, id), claiming: { ...this.state.claiming, [id]: { from, phase: "starting", url: "", at: null } } });
    const reply = await this.post(id, profileOf(asking.pick));
    if (!this.state.claiming[id]) return; // the stream already reported the claim
    if (!reply.ok) {
      this.set({ claiming: without(this.state.claiming, id), failed: { ...this.state.failed, [id]: { from, reason: reply.reason, url: "", refused: false } } });
      return;
    }
    this.set({ claiming: { ...this.state.claiming, [id]: { from, phase: "waiting", url: reply.url, at: reply.at } } });
    this.refuse(id);
  }

  dismiss(id: string) {
    this.set({ failed: without(this.state.failed, id) });
  }

  /** The streamed board and its refused claims: a claimed card's mark clears once it leaves its lane, a refusal made after its start returns it. */
  sync(cards: KanbanTask[], claims: Claims) {
    this.claims = claims;
    const lane = new Map(cards.map((c) => [c.id, c.lane]));
    const moved = (entry: { from: string }, id: string) => lane.has(id) && lane.get(id) !== entry.from;
    const claiming = Object.fromEntries(Object.entries(this.state.claiming).filter(([id, c]) => !moved(c, id)));
    const failed = Object.fromEntries(Object.entries(this.state.failed).filter(([id, f]) => !moved(f, id)));
    if (Object.keys(claiming).length !== Object.keys(this.state.claiming).length || Object.keys(failed).length !== Object.keys(this.state.failed).length) {
      this.set({ claiming, failed });
    }
    for (const id of Object.keys(this.state.claiming)) this.refuse(id);
  }

  /** Return a waiting card when the writer refused its claim at or after its start; an older refusal belongs to an earlier start. */
  private refuse(id: string) {
    const entry = this.state.claiming[id];
    const refusal = this.claims[id];
    if (!entry || entry.at === null || !refusal || refusal.at < entry.at) return;
    this.set({
      claiming: without(this.state.claiming, id),
      failed: { ...this.state.failed, [id]: { from: entry.from, reason: refusal.reason, url: entry.url, refused: true } },
    });
  }
}

/** POST the start to the server, which saves a changed assignee and asks the session-start service for the session. */
export async function postStart(task: string, assignee: string, fetcher: typeof apiFetch = apiFetch): Promise<StartReply> {
  let response: Response;
  try {
    response = await fetcher("/api/start", { method: "POST", body: JSON.stringify({ task, assignee }) });
  } catch {
    return { ok: false, reason: "the start did not reach the server" };
  }
  const body: { url?: string; at?: number; error?: string } | null = await response.json().catch(() => null);
  if (response.ok && body?.url && typeof body.at === "number") return { ok: true, url: body.url, at: body.at };
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}` };
}

/** The configured harnesses; none when the server cannot say, and then the question offers only Work it manually. */
export async function fetchHarnesses(fetcher: typeof apiFetch = apiFetch): Promise<Harnesses> {
  try {
    const response = await fetcher("/api/harnesses");
    if (response.ok) return (await response.json()) as Harnesses;
  } catch {
    // fall through: no harnesses
  }
  return NO_HARNESSES;
}
