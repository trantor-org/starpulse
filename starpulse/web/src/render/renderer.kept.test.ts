// @vitest-environment jsdom
// A page reloaded while the server is down draws the Board the last page kept in browser storage, dated, instead of an empty one; the
// server coming back replaces it and clears the date.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";

/** The browser's storage, which outlives the page "reloaded" below. */
const storage = vi.hoisted(() => ({ held: null as unknown }));
vi.mock("../api/savedSnapshot", () => ({
  browserCache: () => ({
    read: async () => storage.held ?? null,
    write: async (snap: unknown) => void (storage.held = structuredClone(snap)),
  }),
}));
vi.mock("./fonts", () => ({
  loadFonts: () => Promise.resolve(),
  loadLateFonts: () => Promise.resolve(),
}));

class FakeSource {
  static made: FakeSource[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((e: { data: string }) => void)[]>();
  constructor(readonly url: string) {
    FakeSource.made.push(this);
  }
  addEventListener(type: string, fn: (e: { data: string }) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  send(type: string, data: unknown) {
    for (const fn of this.listeners.get(type) ?? []) fn({ data: JSON.stringify(data) });
  }
  close() {
    this.readyState = 2;
  }
}
const server = () => FakeSource.made[FakeSource.made.length - 1];

const machine: Machine = {
  states: ["ready", "in_progress", "review"].map((id, i) => ({ id, name: id, initial: i === 0, final: false })),
  transitions: [],
};
const task = (id: string, state: string): RawTask => ({ id, title: `Title of ${id}`, state, model: "@agent-standard-high", labels: [] });
const board = (): Snapshot => ({
  graphs: ["board"],
  flows: [{ name: "board", agents: [task("TASK-1", "ready"), task("TASK-2", "in_progress"), task("TASK-3", "review")], machine }],
  dags: [],
  domains: [],
  cues: [],
  settled: {},
  error: null,
  now: 1_700_000_000,
});

function stubContext(cv: HTMLCanvasElement) {
  const store: Record<string, unknown> = {};
  const cx = new Proxy({} as Record<string, unknown>, {
    get: (_, p: string) => {
      if (p in store) return store[p];
      if (p === "canvas") return cv;
      if (p === "createRadialGradient" || p === "createLinearGradient") return () => ({ addColorStop() {} });
      if (p === "measureText") return (s: string) => ({ width: String(s).length * 6 });
      return () => {};
    },
    set: (_, p: string, v) => ((store[p] = v), true),
  }) as unknown as CanvasRenderingContext2D;
  vi.spyOn(cv, "getContext").mockReturnValue(cx);
}

/** A page load: fresh modules, as a reload gives, over the same browser storage. */
async function load() {
  vi.resetModules();
  document.body.innerHTML = `<canvas id="c"></canvas><div id="tip"></div><div id="panel"></div><aside id="rail"></aside><nav id="crumb"></nav>`;
  const [{ renderer }, { HudStore }, { loadHudViews }] = await Promise.all([import("./renderer"), import("./hud"), import("./hudViews")]);
  await loadHudViews();
  const cv = document.getElementById("c") as HTMLCanvasElement;
  stubContext(cv);
  const hud = new HudStore();
  const page = renderer(cv, hud, { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
  page.start();
  await vi.advanceTimersByTimeAsync(0);
  return { hud, page };
}
const cardIds = (hud: { get(): { cards: { id: string }[] } }) => hud.get().cards.map((c) => c.id).sort();

describe("a page reloaded while the server is down", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeSource.made = [];
    storage.held = null;
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 200 });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 800 });
    vi.stubGlobal("EventSource", FakeSource);
    vi.stubGlobal("devicePixelRatio", 1);
    vi.stubGlobal("innerWidth", 1400);
    vi.stubGlobal("innerHeight", 900);
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("connection refused"))));
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("draws every card from the snapshot the last page kept, dated and marked stale, and the server's own replaces them", async () => {
    const first = await load();
    server().send("snapshot", board());
    await vi.advanceTimersByTimeAsync(1500);
    expect(cardIds(first.hud)).toEqual(["TASK-1", "TASK-2", "TASK-3"]);
    first.page.stop();

    // the server is down for the reload: its connection fails at once
    const reloaded = await load();
    await vi.advanceTimersByTimeAsync(50);
    const [cards, note] = [cardIds(reloaded.hud), reloaded.hud.get().note];
    server().onerror?.();
    await vi.advanceTimersByTimeAsync(5000);

    expect(cards).toEqual(["TASK-1", "TASK-2", "TASK-3"]);
    expect(note).toMatch(/^stale · \d+:\d\d MST$/);
    expect(cardIds(reloaded.hud)).toEqual(["TASK-1", "TASK-2", "TASK-3"]);
    expect(reloaded.hud.get().note).toMatch(/^retrying · \d+:\d\d MST$/);
    expect(reloaded.hud.get().live).toBe("wait");

    // the server is back: its snapshot is the Board, and the dot is live with no note
    server().onopen?.();
    server().send("snapshot", { ...board(), flows: [{ ...board().flows[0], agents: [task("TASK-1", "review")] }] });
    await vi.advanceTimersByTimeAsync(200);
    expect(cardIds(reloaded.hud)).toEqual(["TASK-1"]);
    expect([reloaded.hud.get().live, reloaded.hud.get().note]).toEqual(["on", ""]);
    reloaded.page.stop();
  });
});
