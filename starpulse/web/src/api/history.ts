// The fetch cache behind the hover back-trace: one /graphql read per task (and flow), shared by the card and the panel.
import { apiFetch } from "./apiFetch";
import type { LaneStep, MachineEvent, MachineStep } from "../features/level/trace";

export type Loaded<T> = T | "loading" | "unavailable";
export interface MachineHistory {
  path: MachineStep[];
  steps: number;
}

export interface History {
  lane(task: string): Loaded<LaneStep[]>;
  machine(task: string, machine: string): Loaded<MachineHistory>;
  /** Every machine event of the task in the last 24 hours, oldest first: the drill-in's replay. */
  replay(task: string): Loaded<MachineEvent[]>;
}

export interface HistoryOptions {
  /** Called once a read lands or fails, so the card and the panel redraw. */
  onChange: () => void;
  fetch?: (url: string, init: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }>;
  now?: () => number;
  /** How long a read is fresh, in seconds. */
  ttl?: number;
}

interface Entry {
  value: unknown;
  at: number;
  busy: boolean;
}
interface Task {
  lanePath?: LaneStep[];
  machinePath?: MachineHistory;
  events?: MachineEvent[];
}

const LANE = "query HistoryLane($id: ID!) { task(id: $id) { lanePath { at from to } } }";
const MACHINE =
  "query HistoryMachine($id: ID!, $machine: String!) { task(id: $id) { machinePath(machine: $machine) { steps path { at event state } } } }";
const REPLAY =
  "query HistoryReplay($id: ID!, $since: Float!) { task(id: $id) { events(since: $since) { at machine event from to } } }";
const DAY = 24 * 3600;

export function createHistory({ onChange, fetch: post = (u, i) => apiFetch(u, i), now = () => Date.now() / 1000, ttl = 30 }: HistoryOptions): History {
  const cache = new Map<string, Entry>();
  /** The cached read, started when absent and again once stale; a stale one keeps answering until the new read lands. A task the board does not hold reads as the empty answer. */
  function read<T>(key: string, query: string, variables: () => object, pick: (task: Task) => T | undefined, empty: T): Loaded<T> {
    const e = cache.get(key) ?? { value: "loading", at: -Infinity, busy: false };
    cache.set(key, e);
    if (!e.busy && now() - e.at >= ttl) {
      e.busy = true;
      post("/graphql", { method: "POST", body: JSON.stringify({ query, variables: variables() }) })
        .then((r): unknown =>
          r.ok
            ? r.json().then((b) => {
                const body = b as { data?: { task: Task | null } | null; errors?: unknown };
                return body.errors || !body.data ? "unavailable" : (body.data.task && pick(body.data.task)) ?? empty;
              })
            : "unavailable",
        )
        .catch(() => "unavailable")
        .then((value) => Object.assign(e, { value, at: now(), busy: false }))
        .then(onChange);
    }
    return e.value as Loaded<T>;
  }
  return {
    lane: (id) => read(`lane ${id}`, LANE, () => ({ id }), (t) => t.lanePath, []),
    machine: (id, machine) =>
      read(`machine ${id} ${machine}`, MACHINE, () => ({ id, machine }), (t) => t.machinePath, { path: [], steps: 0 }),
    replay: (id) => read(`replay ${id}`, REPLAY, () => ({ id, since: now() - DAY }), (t) => t.events, []),
  };
}
