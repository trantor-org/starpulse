// The orbit card's data: /api/level, fetched once a minute, and its mapping onto the orbit's input.
import { apiFetch } from "../../api/apiFetch";
import type { Drift, OrbitInput, SunMode } from "./orbit";
import type { Measure, Pace } from "../../render/comets";

const DAY = 86400;
const HOURS = 168;
const REFRESH_MS = 60_000;

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

/** The level's answer, refreshed on a timer, for `useSyncExternalStore`. */
export class LevelStore {
  private state: LevelState = { kind: "loading" };
  private listeners = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | undefined;

  constructor(private load: () => Promise<LevelState> = () => fetchLevel(), refreshMs = REFRESH_MS) {
    if (refreshMs > 0) this.timer = setInterval(() => void this.refresh(), refreshMs);
  }

  get = () => this.state;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  async refresh() {
    this.state = await this.load();
    // a server with no level will not grow one while the page is open: a reload asks again
    if (this.state.kind === "none") clearInterval(this.timer);
    for (const fn of this.listeners) fn();
  }
  dispose() {
    clearInterval(this.timer);
  }
}
