// @vitest-environment jsdom
// The Star Map shows the sky as it stands when it is seen again: the phase branches drew no frame while the tab was hidden, another view was
// shown or the stream dropped, so the first Board frame after places every dot where the sky now puts it instead of playing the steps it missed.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Machine, RawTask, Snapshot } from "../api";
import { HudStore } from "./hud";

const push = vi.hoisted(() => ({ handlers: null as null | { snapshot: (s: Snapshot) => void; live: (on: boolean) => void } }));
const log = vi.hoisted(() => [] as string[]);

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
vi.mock("./transit", async (actual) => {
  const real = await actual<typeof import("./transit")>();
  return {
    ...real,
    placeBranches: (...a: Parameters<typeof real.placeBranches>) => (log.push("place"), real.placeBranches(...a)),
    resyncBranches: () => (log.push("resync"), real.resyncBranches()),
  };
});

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
  vi.spyOn(cv, "getContext").mockReturnValue(cx);
}

let hidden = false;
const setHidden = (on: boolean) => {
  hidden = on;
  document.dispatchEvent(new Event("visibilitychange"));
};
/** Let the page draw its frames, then hand back what the phase branches were asked to do meanwhile. */
const frames = async () => {
  log.length = 0;
  await vi.advanceTimersByTimeAsync(200);
  return [...log];
};

describe("the Star Map seen again", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    push.handlers = null;
    hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
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

  async function open() {
    const { renderer } = await import("./renderer");
    const cv = document.getElementById("c") as HTMLCanvasElement;
    stubContext(cv);
    const r = renderer(cv, new HudStore(), { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
    r.start();
    await vi.advanceTimersByTimeAsync(0);
    push.handlers!.snapshot(snap("ready"));
    await frames();
    return r;
  }

  it("plays a move made while it is watched", async () => {
    const r = await open();
    push.handlers!.snapshot(snap("in_progress"));
    const did = await frames();
    expect(did).toContain("place");
    expect(did).not.toContain("resync");
    r.stop();
  });

  it("places what changed while the tab was hidden as it stands, once the returning tab's snapshot arrives", async () => {
    const r = await open();
    setHidden(true);
    setHidden(false);
    // the frames drawn before the fresh snapshot still show the last sky, so nothing is placed afresh yet
    expect(await frames()).not.toContain("resync");
    push.handlers!.snapshot(snap("review"));
    const did = await frames();
    expect(did.indexOf("resync")).toBeGreaterThanOrEqual(0);
    expect(did.indexOf("resync")).toBeLessThan(did.indexOf("place"));
    // the sky after it plays its moves again
    push.handlers!.snapshot(snap("in_progress"));
    expect(await frames()).not.toContain("resync");
    r.stop();
  });

  it("places what changed behind another view as it stands when the Star Map is shown again", async () => {
    const r = await open();
    r.show(false);
    push.handlers!.snapshot(snap("in_progress"));
    push.handlers!.snapshot(snap("review"));
    expect(await frames()).not.toContain("place");
    r.show(true);
    const did = await frames();
    expect(did[0]).toBe("resync");
    expect(did).toContain("place");
    r.stop();
  });

  it("places what changed while another level was open as it stands on returning to the Board", async () => {
    const r = await open();
    // a level change snapshots the canvas onto a fresh one, which draws with the same stub
    const cx = (document.getElementById("c") as HTMLCanvasElement).getContext("2d")!;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(cx);
    r.go([{ kind: "board" }, { kind: "state", id: "in_progress" }]);
    await frames();
    push.handlers!.snapshot(snap("in_progress"));
    push.handlers!.snapshot(snap("review"));
    expect(await frames()).not.toContain("place");
    r.go([{ kind: "board" }]);
    const did = await frames();
    expect(did.indexOf("resync")).toBeGreaterThanOrEqual(0);
    expect(did.indexOf("resync")).toBeLessThan(did.indexOf("place"));
    r.stop();
  });

  /** A window that is visible and blurred but paints no frames (an occluded or throttled one): the stream stays open and `document.hidden` stays false. */
  function stallFrames() {
    const real = globalThis.requestAnimationFrame, held: FrameRequestCallback[] = [];
    let stalled = true;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => (stalled ? (held.push(cb), held.length) : real(cb)));
    return () => {
      stalled = false;
      for (const cb of held.splice(0)) real(cb);
    };
  }

  it("places the moves a visible but frameless window banked as they stand, not as a burst", async () => {
    const r = await open();
    const resume = stallFrames();
    window.dispatchEvent(new Event("blur"));
    await vi.advanceTimersByTimeAsync(1500);
    push.handlers!.snapshot(snap("in_progress"));
    await vi.advanceTimersByTimeAsync(1500);
    push.handlers!.snapshot(snap("review"));
    await vi.advanceTimersByTimeAsync(12_000);
    expect(document.hidden).toBe(false);
    log.length = 0;
    resume();
    window.dispatchEvent(new Event("focus"));
    const did = await frames();
    expect(did.indexOf("resync")).toBeGreaterThanOrEqual(0);
    expect(did.indexOf("resync")).toBeLessThan(did.indexOf("place"));
    r.stop();
  });

  it("places what a dropped stream missed as it stands, from the reconnect's snapshot", async () => {
    const r = await open();
    push.handlers!.live(false);
    push.handlers!.snapshot(snap("review"));
    const did = await frames();
    expect(did.indexOf("resync")).toBeGreaterThanOrEqual(0);
    expect(did.indexOf("resync")).toBeLessThan(did.indexOf("place"));
    r.stop();
  });
});
