// The level a demo page answers /api/level with: the same shape the server sends, over a week of invented runs, so the
// orbit card, its gate and its drift badge all render with no server behind the page.
import type { LevelResponse } from "./levelData";

const DAY = 86400;
const HISTORY_S = 30 * DAY;
const TERMINALS = [{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }, { id: "needs_attention", role: "parked" }];
const WORKING = ["ready", "in_progress", "review", "waiting"];
const AGING_S = 3 * DAY;

interface Spec {
  id: string;
  shared: boolean;
  wip: number;
  ended: Record<string, number>;
  /** Task-days its runs spent in each working state. */
  days: Record<string, number>;
  drift?: { added: string[]; removed: string[] };
}
const SOURCES: Spec[] = [
  { id: "claude-code", shared: true, wip: 9, ended: { done: 31, archived: 4, needs_attention: 3 }, days: { ready: 6, in_progress: 41, review: 9, waiting: 3 } },
  { id: "codex-review", shared: true, wip: 5, ended: { done: 12, archived: 9, needs_attention: 1 }, days: { ready: 4, in_progress: 14, review: 22, waiting: 6 }, drift: { added: ["triage"], removed: ["waiting"] } },
  { id: "ci-runner", shared: true, wip: 3, ended: { done: 17, archived: 2, needs_attention: 6 }, days: { ready: 2, in_progress: 8, review: 3, waiting: 19 } },
  { id: "unattributed", shared: false, wip: 2, ended: { done: 6, archived: 5, needs_attention: 1 }, days: { ready: 1, in_progress: 5, review: 2, waiting: 2 } },
];

const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
const share = (o: Record<string, number>) => {
  const n = sum(o);
  return n ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v / n])) : {};
};

/** The server's answer for `hours`, with the refusals and the sun mode the page's address asks for (`?gate=expired|refused`, `?suns=working`, `?pace=`, `?measure=`). */
export function demoLevel(now: number, hours: number, page: URLSearchParams): { status: number; body: LevelResponse & { error?: string; history_s: number } } {
  const window_s = hours * 3600;
  const empty = { history_s: HISTORY_S } as LevelResponse & { error?: string; history_s: number };
  if (page.get("gate") === "expired") return { status: 401, body: { ...empty, error: "sign in" } };
  if (page.get("gate") === "refused") return { status: 403, body: { ...empty, error: "Your account is not in the platform team." } };
  if (window_s > HISTORY_S) return { status: 400, body: { ...empty, error: `window longer than the ${HISTORY_S / DAY}-day history` } };

  const suns = page.get("suns") === "working" ? "working" : "terminal";
  const arrivals = SOURCES.flatMap((s, si) =>
    Object.entries(s.ended).flatMap(([state, n], ti) =>
      // spread over the window by the golden ratio, so no source's arrivals bunch and the replay is the same every load
      Array.from({ length: n }, (_, i) => ({ source: s.id, state, at: now - window_s * (((i + 1) * 0.6180339887 + si * 0.37 + ti * 0.113) % 1) })),
    ),
  ).sort((a, b) => a.at - b.at);
  const endedBy = (state: string) => SOURCES.reduce((a, s) => a + (s.ended[state] ?? 0), 0);
  const daysIn = (state: string) => SOURCES.reduce((a, s) => a + (s.days[state] ?? 0), 0) * DAY;
  const visits = (s: Spec) => Math.max(1, sum(s.ended));
  // each source's open runs, in the states it spends its time in, aged up to six days by the same golden-ratio spread
  const runs = SOURCES.flatMap((s, si) =>
    Array.from({ length: s.wip }, (_, i) => {
      const f = ((i + 1) * 0.6180339887 + si * 0.29) % 1, pick = f * sum(s.days);
      let acc = 0;
      const state = WORKING.find((w) => (acc += s.days[w]) > pick) ?? WORKING[WORKING.length - 1];
      return { source: s.id, task: `DEMO-${200 + si * 20 + i}`, state, age_s: Math.round(6 * DAY * ((f * 7.31) % 1)) };
    }),
  ).sort((a, b) => b.age_s - a.age_s).map((r) => ({ ...r, over: r.age_s > AGING_S }));
  const open: Record<string, number> = {};
  for (const r of runs) open[r.state] = (open[r.state] ?? 0) + 1;
  return {
    status: 200,
    body: {
      now,
      window_s,
      history_s: HISTORY_S,
      machine: "task",
      goal: "done",
      level: {
        title: "Platform runs",
        subject: "task",
        runs: "runs",
        gates: ["review"],
        terminals: TERMINALS,
        orbit: { suns, working: WORKING },
        facets: [{ id: "team", label: "Team" }],
        activity: { measure: page.get("measure") === "count" ? "count" : "share", pace: page.get("pace") === "fast" ? "fast" : page.get("pace") === "live" ? "live" : "min" },
      },
      wip: { count: SOURCES.reduce((a, s) => a + s.wip, 0), states: open },
      throughput: { count: endedBy("done"), per_day: endedBy("done") / (window_s / DAY) },
      time_in_state: WORKING.map((id) => {
        const n = SOURCES.reduce((a, s) => a + visits(s), 0);
        return { id, visits: n, task_s: daysIn(id), mean_s: daysIn(id) / n };
      }),
      aging: { threshold_s: AGING_S, runs },
      orbit: {
        suns,
        terminals: Object.fromEntries(TERMINALS.map((t) => [t.id, { ended: endedBy(t.id) }])),
        working: Object.fromEntries(WORKING.map((state) => [state, { task_s: daysIn(state) }])),
      },
      arrivals,
      sources: SOURCES.map((s) => ({
        id: s.id,
        shared: s.shared,
        wip: s.wip,
        ended: s.ended,
        terminal_share: share(s.ended),
        dwell: Object.fromEntries(WORKING.map((state) => [state, { visits: visits(s), task_s: s.days[state] * DAY, mean_s: (s.days[state] * DAY) / visits(s) }])),
        time_share: share(s.days),
        ...(s.drift ? { drift: s.drift } : {}),
      })),
    },
  };
}
