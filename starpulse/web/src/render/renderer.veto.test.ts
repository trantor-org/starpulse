// @vitest-environment jsdom
// A path the page vetoes is never opened: the click that asked for it is handed to the page, which shows its own view instead.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";
import { HudStore } from "./hud";
import { BOARD, type Path } from "./levels";
import type { Renderer } from "./rendererTypes";

const push = vi.hoisted(() => ({ handlers: null as null | { snapshot: (s: Snapshot) => void; live: (on: boolean) => void } }));

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
const machine = (ids: string[]): Machine => ({
  states: ids.map((id, i) => ({ id, name: id, initial: i === 0, final: false })),
  transitions: [],
});
const task = (id: string, state: string): RawTask => ({ id, title: id, state, model: "@agent-standard-high", labels: [] });
const snap = (state: string): Snapshot => ({
  graphs: ["board"],
  flows: [{ name: "board", agents: [task("TASK-1", state)], machine: machine(["ready", "in_progress", "review"]) }],
  dags: [],
  domains: [],
  cues: [],
  settled: {},
  error: null,
  now: 1_700_000_000,
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
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(cx);
}

const IN_PROGRESS = [...BOARD, { kind: "state", id: "in_progress" } as const];

describe("a vetoed path", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.handlers = null;
    document.body.innerHTML = `<canvas id="c"></canvas><div id="tip"></div><div id="panel"></div><aside id="rail"></aside><nav id="crumb"></nav>`;
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 200 });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 800 });
    vi.stubGlobal("devicePixelRatio", 1);
    vi.stubGlobal("innerWidth", 1400);
    vi.stubGlobal("innerHeight", 900);
    localStorage.clear();
    vi.resetModules();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  async function open(beforeSnapshot?: (r: Renderer) => void) {
    const { renderer } = await import("./renderer");
    const cv = document.getElementById("c") as HTMLCanvasElement;
    stubContext(cv);
    const hud = new HudStore();
    const r = renderer(cv, hud, { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
    beforeSnapshot?.(r);
    r.start();
    await vi.advanceTimersByTimeAsync(0);
    push.handlers!.snapshot(snap("in_progress"));
    await vi.advanceTimersByTimeAsync(200);
    return { r, hud };
  }

  it("opens the level when nothing vetoes it", async () => {
    const { r, hud } = await open();
    r.go(IN_PROGRESS);
    expect(hud.get().path).toEqual(IN_PROGRESS);
    r.stop();
  });

  it("hands the path to the veto and stays on the level showing", async () => {
    const seen: Path[] = [];
    const { r, hud } = await open();
    r.intercept((p) => (seen.push(p), true));
    r.go(IN_PROGRESS);
    expect(seen).toEqual([IN_PROGRESS]);
    expect(hud.get().path).toEqual(BOARD);
    r.stop();
  });

  it("opens a path the veto lets through", async () => {
    const { r, hud } = await open();
    r.intercept(() => false);
    r.go(IN_PROGRESS);
    expect(hud.get().path).toEqual(IN_PROGRESS);
    r.stop();
  });

  it("starts on the Board when the level the tab last showed is vetoed", async () => {
    localStorage.setItem("fv.path", JSON.stringify(IN_PROGRESS));
    const seen: Path[] = [];
    const { hud, r } = await open((x) => x.intercept((p) => (seen.push(p), true)));
    expect(seen).toEqual([IN_PROGRESS]);
    expect(hud.get().path).toEqual(BOARD);
    r.stop();
  });
});
