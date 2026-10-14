import { describe, expect, it, vi } from "vitest";
import { fetchLevel, LevelStore, orbitInput, pushLevelStatus, type LevelResponse, type LevelState } from "./levelData";

const level = (): LevelResponse => ({
  now: 1,
  window_s: 86400,
  history_s: 86400,
  machine: "board",
  goal: "done",
  level: {
    title: "Flow",
    subject: "tasks",
    runs: "runs",
    gates: [],
    terminals: [{ id: "done", role: "goal" }],
    orbit: { suns: "terminal", working: ["in_progress"] },
    facets: [],
    activity: { measure: "share", pace: "live" },
  },
  wip: { count: 0, states: {} },
  throughput: { count: 0, per_day: 0 },
  time_in_state: [],
  aging: { threshold_s: null, runs: [] },
  orbit: { suns: "terminal", terminals: { done: { ended: 1 } }, working: { in_progress: { task_s: 0 } } },
  arrivals: [],
  sources: [
    {
      id: "trantor",
      shared: true,
      wip: 0,
      ended: { done: 1 },
      terminal_share: { done: 1 },
      dwell: {},
      time_share: {},
      drift: { added: ["triage"], removed: [] },
    },
    {
      id: "unattributed",
      shared: false,
      wip: 0,
      ended: {},
      terminal_share: {},
      dwell: {},
      time_share: {},
    },
  ],
});

describe("fetchLevel", () => {
  it("maps HTTP statuses onto LevelState", async () => {
    const ok = await fetchLevel(async () => new Response(JSON.stringify(level()), { status: 200 }));
    expect(ok).toEqual({ kind: "ok", level: level() });
    expect(await fetchLevel(async () => new Response("{}", { status: 404 }))).toEqual({ kind: "none" });
    expect(await fetchLevel(async () => new Response("{}", { status: 401 }))).toEqual({ kind: "gate", why: "expired" });
  });
});

describe("orbitInput", () => {
  it("maps sources onto orbit pace and reach", () => {
    const o = orbitInput(level(), (s) => s, 1);
    expect(o.sources[0].drift).toEqual({ added: ["triage"], removed: [] });
    expect(o.sources[1]).toMatchObject({ id: "unattributed", name: "unattributed", shared: false });
  });
});

describe("LevelStore", () => {
  it("holds loading until the first answer and tells its listeners each one", async () => {
    const seen: string[] = [];
    let n = 0;
    const store = new LevelStore(async () => (++n === 1 ? { kind: "none" } : { kind: "ok", level: level() }));
    expect(store.get().kind).toBe("loading");
    store.subscribe(() => seen.push(store.get().kind));
    await store.refresh();
    await store.refresh();
    expect(seen).toEqual(["none", "ok"]);
    store.dispose();
  });

  it("does not poll on a timer; stream events refresh the body without a GET", async () => {
    let asked = 0;
    const store = new LevelStore(async () => (asked++, { kind: "ok", level: level() }));
    await store.refresh();
    expect(asked).toBe(1);
    asked = 0;
    pushLevelStatus(level());
    expect(asked).toBe(0);
    expect(store.get().kind).toBe("ok");
    store.dispose();
  });

  describe("while the Orbit view is hidden", () => {
    const answered = async (): Promise<LevelState> => ({ kind: "ok", level: level() });

    it("asks nothing on a timer; asks when shown without an ok body; stream updates without GET", async () => {
      vi.useFakeTimers();
      let asked = 0;
      const store = new LevelStore(async () => (asked++, answered()));
      await store.refresh();
      expect(asked).toBe(1);

      await vi.advanceTimersByTimeAsync(5 * 60_000);
      expect(asked).toBe(1);

      store.setActive(true);
      await vi.advanceTimersByTimeAsync(0);
      expect(asked).toBe(1);

      asked = 0;
      pushLevelStatus(level());
      expect(asked).toBe(0);

      store.setActive(false);
      await vi.advanceTimersByTimeAsync(5 * 60_000);
      expect(asked).toBe(0);
      store.dispose();
      vi.useRealTimers();
    });

    it("leaves the first answer to the page's own first ask when the view is shown before it lands", async () => {
      let asked = 0;
      const store = new LevelStore(async () => (asked++, answered()));
      const first = store.refresh();
      store.setActive(true);
      await first;
      expect(asked).toBe(1);
      store.dispose();
    });

    it("ignores stream events once disposed", async () => {
      const store = new LevelStore(async () => ({ kind: "ok", level: level() }));
      await store.refresh();
      store.dispose();
      const before = store.get();
      pushLevelStatus({ ...level(), now: 99 });
      expect(store.get()).toBe(before);
    });
  });
});
