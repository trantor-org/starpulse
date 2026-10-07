import { describe, expect, it } from "vitest";
import { fetchLevel, LevelStore, orbitInput, type LevelResponse } from "./levelData";

const DAY = 86400;
const level = (over: Partial<LevelResponse> = {}): LevelResponse => ({
  now: 1e9,
  window_s: 7 * DAY,
  history_s: 30 * DAY,
  machine: "task",
  goal: "done",
  level: {
    title: "Runs",
    subject: "task",
    runs: "runs",
    gates: ["review"],
    terminals: [{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }],
    orbit: { suns: "terminal", working: ["ready", "in_progress"] },
    facets: [],
    activity: { measure: "share", pace: "live" },
  },
  wip: { count: 3, states: {} },
  throughput: { count: 14, per_day: 2 },
  time_in_state: [],
  aging: { threshold_s: null, runs: [] },
  orbit: {
    suns: "terminal",
    terminals: { done: { ended: 14 }, archived: { ended: 6 } },
    working: { ready: { task_s: 2 * DAY }, in_progress: { task_s: 5 * DAY } },
  },
  arrivals: [{ source: "a", state: "done", at: 1e9 - DAY }],
  sources: [
    {
      id: "a", shared: true, wip: 2, ended: { done: 10, archived: 4 },
      terminal_share: { done: 10 / 14, archived: 4 / 14 },
      dwell: { ready: { visits: 3, task_s: 2 * DAY, mean_s: 1 }, in_progress: { visits: 3, task_s: 5 * DAY, mean_s: 2 } },
      time_share: { ready: 2 / 7, in_progress: 5 / 7 },
    },
    { id: "unattributed", shared: false, wip: 1, ended: { done: 4, archived: 2 }, terminal_share: { done: 4 / 6, archived: 2 / 6 }, dwell: {}, time_share: {} },
  ],
  ...over,
});

const reply = (status: number, body: unknown) => (async () => ({ status, ok: status < 400, json: async () => body })) as unknown as typeof fetch;

describe("fetchLevel", () => {
  it("is none for a server with no level, so the view stays out of the navigator", async () => {
    expect(await fetchLevel(reply(404, { error: "no level" }))).toEqual({ kind: "none" });
  });

  it("is the sign-in gate for an expired session and the refused gate, with its reason, for a signed-in refusal", async () => {
    expect(await fetchLevel(reply(401, { error: "sign in" }))).toEqual({ kind: "gate", why: "expired" });
    expect(await fetchLevel(reply(403, { error: "not in the team" }))).toEqual({ kind: "gate", why: "refused", reason: "not in the team" });
  });

  it("is a message for a history that keeps no runs and for any other failure", async () => {
    expect(await fetchLevel(reply(501, { error: "no runs kept" }))).toEqual({ kind: "error", message: "no runs kept" });
    expect(await fetchLevel((async () => { throw new Error("offline"); }) as unknown as typeof fetch)).toEqual({ kind: "error", message: "offline" });
  });

  it("asks again for the whole history when the window is longer than it", async () => {
    const urls: string[] = [];
    const f = (async (url: string) => {
      urls.push(url);
      return urls.length === 1
        ? { status: 400, ok: false, json: async () => ({ error: "window past history", history_s: 3 * DAY }) }
        : { status: 200, ok: true, json: async () => level({ window_s: 3 * DAY }) };
    }) as unknown as typeof fetch;
    const got = await fetchLevel(f);
    expect(urls).toEqual(["/api/level?hours=168", "/api/level?hours=72"]);
    expect(got.kind).toBe("ok");
  });

  it("is the answer for a 200", async () => {
    expect(await fetchLevel(reply(200, level()))).toMatchObject({ kind: "ok", level: { machine: "task" } });
  });
});

describe("orbitInput", () => {
  const name = (id: string) => id.toUpperCase();

  it("reads a source's pace from the runs it ended a day and its reach from the working days a run took", () => {
    const o = orbitInput(level(), name, 1.6);
    const a = o.sources[0];
    expect(a).toMatchObject({ id: "a", name: "a", shared: true, wip: 2, perDay: 14 / 7, terminalShare: { done: 10 / 14, archived: 4 / 14 }, timeShare: { ready: 2 / 7, in_progress: 5 / 7 } });
    expect(a.cycleDays).toBeCloseTo(7 / 14, 9);
    expect(o).toMatchObject({ suns: "terminal", working: ["ready", "in_progress"], aspect: 1.6, endedTotals: { done: 14, archived: 6 }, taskDays: { ready: 2, in_progress: 5 } });
    expect(o.terminals).toEqual([{ id: "done", role: "goal" }, { id: "archived", role: "abandoned" }]);
    expect(o.name("done")).toBe("DONE");
  });

  it("gives a source that ended nothing no pace and no reach rather than dividing by zero", () => {
    const quiet = level({ sources: [{ id: "q", shared: true, wip: 1, ended: {}, terminal_share: {}, dwell: {}, time_share: {} }] });
    expect(orbitInput(quiet, name, 1)).toMatchObject({ sources: [{ perDay: 0, cycleDays: 0 }] });
  });

  it("names a shared source by its id and the unattributed aggregate as such, and carries a drift through", () => {
    const drifted = level();
    drifted.sources[0].drift = { added: ["triage"], removed: [] };
    const o = orbitInput(drifted, name, 1);
    expect(o.sources[0].drift).toEqual({ added: ["triage"], removed: [] });
    expect(o.sources[1]).toMatchObject({ id: "unattributed", name: "unattributed", shared: false });
  });
});

describe("LevelStore", () => {
  it("holds loading until the first answer and tells its listeners each one", async () => {
    const seen: string[] = [];
    let n = 0;
    const store = new LevelStore(async () => (++n === 1 ? { kind: "none" } : { kind: "ok", level: level() }), 0);
    expect(store.get().kind).toBe("loading");
    store.subscribe(() => seen.push(store.get().kind));
    await store.refresh();
    await store.refresh();
    expect(seen).toEqual(["none", "ok"]);
    store.dispose();
  });
});
