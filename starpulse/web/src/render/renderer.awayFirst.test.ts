// @vitest-environment jsdom
// A page opened on another view (a task link, the Kanban) gets its first snapshot with the Star Map hidden: the Star Map is not laid out
// then, for a layout costs the view being drawn a few hundred milliseconds. It is laid out, as a first one, the moment it is shown.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";
import { HudStore } from "./hud";

const push = vi.hoisted(() => ({ handlers: null as null | { snapshot: (s: Snapshot) => void; live: (on: boolean) => void } }));
const laid = vi.hoisted(() => ({ count: 0 }));

vi.mock("../api/stream", () => ({
  openStream: (handlers: { snapshot: (s: Snapshot) => void; live: (on: boolean) => void }) => {
    push.handlers = handlers;
    return { close: vi.fn() };
  },
}));
vi.mock("./fonts", () => ({
  loadFonts: () => Promise.resolve(),
  loadLateFonts: () => Promise.resolve(),
}));
vi.mock("./scene", async (actual) => {
  const real = await actual<typeof import("./scene")>();
  return { ...real, build: (...a: Parameters<typeof real.build>) => (laid.count++, real.build(...a)) };
});

const machine = (ids: string[]): Machine => ({
  states: ids.map((id, i) => ({ id, name: id, initial: i === 0, final: false })),
  transitions: [],
});
const task = (id: string, state: string): RawTask => ({ id, title: id, state, model: "@agent-standard-high", labels: [] });
const snap = (state: string, now = 1_700_000_000): Snapshot => ({
  graphs: ["board"],
  flows: [{ name: "board", agents: [task("TASK-1", state)], machine: machine(["ready", "in_progress", "review"]) }],
  dags: [],
  domains: [],
  cues: [],
  settled: {},
  error: null,
  now,
});

/** Canvas 2D that accepts every call the Board's layout and frames make. */
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

describe("a Star Map whose first snapshot arrives while another view is shown", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.handlers = null;
    laid.count = 0;
    document.body.innerHTML = `<canvas id="c"></canvas><div id="tip"></div><div id="panel"></div><aside id="rail"></aside><nav id="crumb"></nav>`;
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 200 });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 800 });
    vi.stubGlobal("devicePixelRatio", 1);
    vi.stubGlobal("innerWidth", 1400);
    vi.stubGlobal("innerHeight", 900);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  async function open(away: boolean) {
    const { renderer } = await import("./renderer");
    const cv = document.getElementById("c") as HTMLCanvasElement;
    stubContext(cv);
    const r = renderer(cv, new HudStore(), { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
    r.start();
    if (away) r.show(false);
    await vi.advanceTimersByTimeAsync(0);
    push.handlers!.snapshot(snap("ready"));
    await vi.advanceTimersByTimeAsync(200);
    return r;
  }

  it("lays the Star Map out once it is shown, not when the snapshot arrives", async () => {
    const r = await open(true);
    expect(laid.count).toBe(0);

    r.show(true);

    expect(laid.count).toBe(1);
    r.stop();
  });

  it("lays out a Star Map that is shown from the first snapshot at once", async () => {
    const r = await open(false);

    expect(laid.count).toBeGreaterThan(0);
    r.stop();
  });

  it("opens a task from the hidden Star Map's first layout", async () => {
    const r = await open(true);

    r.openTask("TASK-1");

    expect(laid.count).toBe(1);
    r.stop();
  });
});
