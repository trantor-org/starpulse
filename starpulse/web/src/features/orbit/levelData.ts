// The orbit card's data: /api/level once on show, then `level` events from /api/events.
import { apiFetch } from "../../api/apiFetch";
import type { Drift, OrbitInput, SunMode } from "./orbit";
import type { Measure, Pace } from "../../render/comets";

const DAY = 86400;
const HOURS = 168;

export interface LevelSource {
  id: string;
  shared: boolean;
  wip: number;
  ended: Record<string, number>;
  terminal_share: Record<string, number>;
  dwell: Record<string, { visits: number; task_s: number; mean_s: number | null }>;
  time_share: Record<string, number>;
  /** Machine states the source's runs gained or lost against the config: the drift badge's facts. */
  drift?: Drift;
}

export interface LevelResponse {
  now: number;
  window_s: number;
  history_s: number;
  machine: string;
  goal: string;
  level: {
    title: string;
    subject: string;
    runs: string;
    gates: string[];
    terminals: { id: string; role: string }[];
    orbit: { suns: SunMode; working: string[] };
    facets: { id: string; label: string }[];
    activity: { measure: Measure; pace: Pace };
  };
  wip: { count: number; states: Record<string, number> };
  throughput: { count: number; per_day: number };
  /** Each waiting state's stays inside the window. */
  time_in_state: { id: string; visits: number; task_s: number; mean_s: number | null }[];
  /** The runs now in a working state, oldest first, each flagged `over` past the 85th-percentile cycle time. */
  aging: { threshold_s: number | null; runs: { source: string; task: string; state: string; age_s: number; over: boolean }[] };
  orbit: { suns: SunMode; terminals: Record<string, { ended: number }>; working: Record<string, { task_s: number }> };
  arrivals: { source: string; state: string; at: number }[];
  sources: LevelSource[];
}

/** What the page knows of the level: no level at all, a session to renew or refused, a failure, or the answer. */
export type LevelState =
  | { kind: "loading" }
  | { kind: "none" }
  | { kind: "gate"; why: "expired" | "refused"; reason?: string }
  | { kind: "error"; message: string }
  | { kind: "ok"; level: LevelResponse };

const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);

/** `/api/level` over the last week, or over the whole history when the server has less than a week. */
export async function fetchLevel(f: (url: string) => Promise<Response> = apiFetch, hours = HOURS, retry = true): Promise<LevelState> {
  try {
    const res = await f(`/api/level?hours=${hours}`);
    const body = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    const why = typeof body.error === "string" ? body.error : `/api/level answered ${res.status}`;
    if (res.status === 404) return { kind: "none" };
    if (res.status === 401) return { kind: "gate", why: "expired" };
    if (res.status === 403) return { kind: "gate", why: "refused", reason: why };
    if (res.status === 400 && retry && typeof body.history_s === "number" && body.history_s >= 3600)
      return fetchLevel(f, Math.floor(body.history_s / 3600), false);
    if (!res.ok) return { kind: "error", message: why };
    return { kind: "ok", level: body as unknown as LevelResponse };
  } catch (e) {
    return { kind: "error", message: e instanceof Error ? e.message : String(e) };
  }
}

/** The orbit's input from an answer: a source's pace is the runs it ended a day, its reach the mean working days of a run it ended. */
export function orbitInput(r: LevelResponse, name: (state: string) => string, aspect: number): OrbitInput {
  const days = r.window_s / DAY;
  return {
    suns: r.level.orbit.suns,
    terminals: r.level.terminals,
    working: r.level.orbit.working,
    name,
    endedTotals: Object.fromEntries(Object.entries(r.orbit.terminals).map(([id, t]) => [id, t.ended])),
    taskDays: Object.fromEntries(Object.entries(r.orbit.working).map(([id, w]) => [id, w.task_s / DAY])),
    aspect,
    sources: r.sources.map((s) => {
      const ended = sum(s.ended);
      const worked = Object.values(s.dwell).reduce((a, d) => a + d.task_s, 0);
      return {
        id: s.id,
        name: s.id,
        shared: s.shared,
        wip: s.wip,
        perDay: ended / days,
        cycleDays: ended ? worked / ended / DAY : 0,
        ended: s.ended,
        terminalShare: s.terminal_share,
        timeShare: s.time_share,
        drift: s.drift,
      };
    }),
  };
}

/** Stores that take `/api/events` `level` bodies; the renderer pushes each one. */
const streamListeners = new Set<(body: unknown) => void>();

/** Hand a `level` stream event to every open Orbit store. */
export function pushLevelStatus(body: unknown): void {
  for (const fn of streamListeners) fn(body);
}

/**
 * The level's answer, for `useSyncExternalStore`. It asks once when Orbit is shown, then applies `level` stream events.
 */
export class LevelStore {
  private state: LevelState = { kind: "loading" };
  private listeners = new Set<() => void>();
  private active = false;
  private running: Promise<void> | undefined;
  private again = false;

  constructor(private load: () => Promise<LevelState> = () => fetchLevel()) {
    streamListeners.add(this.accept);
  }

  get = () => this.state;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  /** Apply a level body from the stream; a shape the store refuses leaves the last reading. */
  accept = (body: unknown): void => {
    if (body === null || typeof body !== "object") return;
    this.state = { kind: "ok", level: body as LevelResponse };
    for (const fn of this.listeners) fn();
  };

  /** Whether the Orbit view is shown: a hidden one asks nothing; a shown one GETs once if idle without an ok body (not while the page's first ask is in flight). */
  setActive(on: boolean) {
    if (on === this.active) return;
    this.active = on;
    if (on && this.state.kind !== "ok" && this.state.kind !== "loading") void this.refresh();
  }

  /** Ask once (connect sync); stream events keep it current afterwards. */
  refresh(): Promise<void> {
    if (this.running) {
      this.again = true;
      return this.running;
    }
    return (this.running = this.ask().finally(() => (this.running = undefined)));
  }

  private async ask() {
    do {
      this.again = false;
      this.state = await this.load();
      for (const fn of this.listeners) fn();
    } while (this.again);
  }

  dispose() {
    streamListeners.delete(this.accept);
    this.active = false;
  }
}
