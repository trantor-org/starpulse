// @vitest-environment jsdom
// The Board's working state is never opened as a level: every path into it, from a click, the address or the tab's last level, asks the page to drill into its first task instead.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";
import { HudStore } from "./hud";
import { BOARD } from "./levels";
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
/** A Board whose In Progress state opens the in-progress machine, holding one task per given state. */
const snap = (...states: string[]): Snapshot => ({
  graphs: ["board", "in-progress"],
  flows: [
    { name: "board", agents: states.map((s, i) => task("TASK-" + (i + 1), s)), machine: { ...machine(["ready", "in_progress", "review"]), submachines: [{ state: "in_progress", machine: "in-progress", when: "" }] } },
    { name: "in-progress", parent: null, agents: [], machine: machine(["build", "deliver"]) },
  ],
  roles: { working: "in_progress", ready: "ready" },
  dags: [],
  domains: [],
  cues: [],
  settled: {},
  error: null,
  now: 1_700_000_000,
}) as Snapshot;

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
const REVIEW = [...BOARD, { kind: "state", id: "review" } as const];

describe("the working state", () => {
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
    history.replaceState(null, "", "/");
    vi.resetModules();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    history.replaceState(null, "", "/");
  });

  async function open(board: Snapshot, beforeSnapshot?: (r: Renderer) => void) {
    const { renderer } = await import("./renderer");
    const cv = document.getElementById("c") as HTMLCanvasElement;
    stubContext(cv);
    const hud = new HudStore();
    const r = renderer(cv, hud, { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
    beforeSnapshot?.(r);
    r.start();
    await vi.advanceTimersByTimeAsync(0);
    push.handlers!.snapshot(board);
    await vi.advanceTimersByTimeAsync(200);
    return { r, hud };
  }

  it("asks the page to drill into the lane's first board task instead of opening the level", async () => {
    const drills: string[] = [];
    const { r, hud } = await open(snap("ready", "in_progress", "in_progress"), (x) => x.onDrill((id) => drills.push(id)));
    r.go(IN_PROGRESS);
    expect(drills).toEqual(["TASK-2"]);
    expect(hud.get().path).toEqual(BOARD);
    r.stop();
  });

  it("stays where it is when no task is in the lane", async () => {
    const drills: string[] = [];
    const { r, hud } = await open(snap("ready", "review"), (x) => x.onDrill((id) => drills.push(id)));
    r.go(REVIEW);
    r.go(IN_PROGRESS);
    expect(drills).toEqual([]);
    expect(hud.get().path).toEqual(REVIEW);
    r.stop();
  });

  it("opens every other level as before", async () => {
    const { r, hud } = await open(snap("in_progress"), (x) => x.onDrill(() => {}));
    r.go(REVIEW);
    expect(hud.get().path).toEqual(REVIEW);
    r.stop();
  });

  it("holds a drill asked for before the page registers and hands it over on registration", async () => {
    const { r, hud } = await open(snap("in_progress"));
    r.go(IN_PROGRESS);
    expect(hud.get().path).toEqual(BOARD);
    const drills: string[] = [];
    r.onDrill((id) => drills.push(id));
    expect(drills).toEqual(["TASK-1"]);
    r.stop();
  });

  it("starts on the Board and drills when the tab last showed the working state, even with the page registering after the first snapshot", async () => {
    localStorage.setItem("fv.path", JSON.stringify(IN_PROGRESS));
    const { hud, r } = await open(snap("in_progress"));
    expect(hud.get().path).toEqual(BOARD);
    expect(JSON.parse(localStorage.getItem("fv.path")!)).toEqual(BOARD);
    const drills: string[] = [];
    r.onDrill((id) => drills.push(id));
    expect(drills).toEqual(["TASK-1"]);
    r.stop();
  });

  it.each(["/?open=in-progress", "/flow/in-progress"])("starts on the Board and drills for the deep link %s", async (address) => {
    history.replaceState(null, "", address);
    const drills: string[] = [];
    const { hud, r } = await open(snap("in_progress"), (x) => x.onDrill((id) => drills.push(id)));
    expect(hud.get().path).toEqual(BOARD);
    expect(drills).toEqual(["TASK-1"]);
    r.stop();
  });
});
