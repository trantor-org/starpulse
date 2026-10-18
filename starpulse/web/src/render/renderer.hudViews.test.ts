// @vitest-environment jsdom
// Away-first open (Kanban/DAGs) never paints the canvas, so HUD cards/dagData must load from the first snapshot, not first paint.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";
import { HudStore } from "./hud";

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
  dags: [{ name: "dagu/deliver", status: "succeeded", runId: "r1", startedAt: "", finishedAt: "2026-10-11T00:00:00Z", steps: [] }],
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

describe("Kanban and DAGs HUD fields after the first snapshot", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.snapshot = null;
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

  it("fills cards and dagData when the canvas stays away (Kanban/DAGs first)", async () => {
    const { renderer } = await import("./renderer");
    const hud = new HudStore();
    const cv = document.getElementById("c") as HTMLCanvasElement;
    stubContext(cv);
    const tip = document.getElementById("tip") as HTMLElement;
    const panel = document.getElementById("panel") as HTMLElement;

    const r = renderer(cv, hud, { tip, panel }, false);
    r.show(false); // away before any frame: the path ?view=kanban takes
    r.start();
    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();

    expect(push.snapshot).toBeTruthy();
    push.snapshot!(snap([task("TASK-1", "ready"), task("TASK-2", "in_progress")]));

    // loadHudViews (dynamic import) then staged publish (two setTimeout(0)s)
    await vi.waitFor(async () => {
      await vi.advanceTimersByTimeAsync(0);
      expect(hud.get().cards.map((c) => c.id).sort()).toEqual(["TASK-1", "TASK-2"]);
    });
    expect(hud.get().dagData?.dags.map((d) => d.name)).toEqual(["dagu/deliver"]);
    r.stop();
  });
});
