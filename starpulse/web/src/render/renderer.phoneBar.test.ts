// @vitest-environment jsdom
// At phone width the Board draws before React mounts the view bar along the bottom edge: the first layout must already leave the bar's
// height, or the bar's arrival lays the Board out again and its states and flow lines glide into place with no viewport change.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";
import { HudStore } from "./hud";
import type { Probe } from "./rendererTypes";

const push = vi.hoisted(() => ({ snapshot: null as null | ((s: Snapshot) => void) }));

vi.mock("../api/stream", () => ({
  openStream: (handlers: { snapshot: (s: Snapshot) => void }) => {
    push.snapshot = handlers.snapshot;
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
const snap = (tasks: RawTask[]): Snapshot => ({
  graphs: ["board"],
  flows: [{ name: "board", agents: tasks, machine: machine(["ready", "in_progress", "review"]) }],
  dags: [{ name: "dagu/deliver", status: "succeeded", runId: "r1", startedAt: "", finishedAt: "2026-10-11T00:00:00Z", schedule: [], stats: null, rerun: null, steps: [] }],
  domains: [{ name: "Delivery", dags: [{ name: "dagu/deliver", runSafe: false }] }],
  cues: [],
  settled: {},
  error: null,
  now: 1_700_000_000,
});

/** Canvas 2D that accepts every call the Board's first layout makes. */
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

describe("the phone view bar mounting after the Board's first layout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.snapshot = null;
    document.body.innerHTML = `<canvas id="c"></canvas><div id="tip"></div><div id="panel"></div><nav id="crumb"></nav>`;
    // the phone media query: no navigator or rail, and the bar's height published as --pnav
    document.documentElement.style.setProperty("--nav", "0px");
    document.documentElement.style.setProperty("--pnav", "54px");
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 0 });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get(this: HTMLElement) { return this.id === "pnav" ? 54 : 0; } });
    vi.stubGlobal("devicePixelRatio", 1);
    vi.stubGlobal("innerWidth", 880);
    vi.stubGlobal("innerHeight", 700);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    document.documentElement.removeAttribute("style");
  });

  it("holds the canvas and every state in place when the bar mounts", async () => {
    const { renderer } = await import("./renderer");
    const cv = document.getElementById("c") as HTMLCanvasElement;
    stubContext(cv);
    const r = renderer(cv, new HudStore(), { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
    r.start();
    await vi.advanceTimersByTimeAsync(0);
    push.snapshot!(snap([task("TASK-1", "ready"), task("TASK-2", "in_progress"), task("TASK-3", "review")]));
    await vi.advanceTimersByTimeAsync(5000);
    const probe = (window as unknown as { flowProbe: () => Probe }).flowProbe;
    const first = probe();
    expect(first.states.length).toBe(3);

    document.body.insertAdjacentHTML("beforeend", `<nav id="pnav"></nav>`);
    dispatchEvent(new Event("resize")); // what App's observer sends once the bar is drawn
    await vi.advanceTimersByTimeAsync(5000);

    expect(probe().states).toEqual(first.states);
    expect(probe().canvas).toEqual(first.canvas);
    expect(first.canvas).toEqual({ w: 880, h: 646 });
    r.stop();
  });
});
