// The fetch cache behind the hover back-trace: one /api/history read per task (and flow), shared by the card and the panel.
import { apiFetch } from "./demo";
import type { LaneStep, MachineStep } from "./trace";

export type Loaded<T> = T | "loading" | "unavailable";
export interface MachineHistory {
  path: MachineStep[];
  steps: number;
}

export interface History {
  lane(task: string): Loaded<LaneStep[]>;
  machine(task: string, flow: string): Loaded<MachineHistory>;
}

export interface HistoryOptions {
  /** Called once a read lands or fails, so the card and the panel redraw. */
  onChange: () => void;
  fetch?: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }>;
  now?: () => number;
  /** How long a read is fresh, in seconds. */
  ttl?: number;
}

interface Entry {
  value: unknown;
  at: number;
  busy: boolean;
}
interface Body {
  path: unknown;
  steps?: number;
}

export function createHistory({ onChange, fetch: get = (u) => apiFetch(u), now = () => Date.now() / 1000, ttl = 30 }: HistoryOptions): History {
  const cache = new Map<string, Entry>();
  /** The cached read, started when absent and again once stale; a stale one keeps answering until the new read lands. */
  function read<T>(url: string, pick: (body: Body) => T): Loaded<T> {
    const e = cache.get(url) ?? { value: "loading", at: -Infinity, busy: false };
    cache.set(url, e);
    if (!e.busy && now() - e.at >= ttl) {
      e.busy = true;
      get(url)
        .then((r): unknown => (r.ok ? r.json().then((b) => pick(b as Body)) : "unavailable"))
        .catch(() => "unavailable")
        .then((value) => Object.assign(e, { value, at: now(), busy: false }))
        .then(onChange);
    }
    return e.value as Loaded<T>;
  }
  return {
    lane: (task) => read(`/api/history?task=${task}`, (b) => b.path as LaneStep[]),
    machine: (task, flow) => read(`/api/history?task=${task}&flow=${flow}`, (b) => ({ path: b.path as MachineStep[], steps: b.steps ?? 0 })),
  };
}
