// @vitest-environment jsdom
// A theme change redraws the night sky: the radial wash is cached by canvas size, so before this it kept the old background until the
// canvas was resized.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Snapshot } from "../api";
import { applyTheme } from "../features/admin/theme/apply";
import { BUILTIN, SLATE, build } from "../features/admin/theme/scheme";
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

/** Canvas 2D that records the color stops of every gradient it is asked for, in order. */
function stubContext(cv: HTMLCanvasElement) {
  const store: Record<string, unknown> = {}, washes: string[][] = [];
  const cx = new Proxy({} as Record<string, unknown>, {
    get: (_, p: string) => {
      if (p in store) return store[p];
      if (p === "canvas") return cv;
      if (p === "createRadialGradient") {
        return () => {
          const stops: string[] = [];
          washes.push(stops);
          return { addColorStop: (_at: number, color: string) => stops.push(color) };
        };
      }
      if (p === "createLinearGradient") return () => ({ addColorStop() {} });
      if (p === "measureText") return (s: string) => ({ width: String(s).length * 6 });
      return () => {};
    },
    set: (_, p: string, v) => ((store[p] = v), true),
  }) as unknown as CanvasRenderingContext2D;
  vi.spyOn(cv, "getContext").mockReturnValue(cx);
  return washes;
}

describe("the night sky after a theme change", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = `<canvas id="c"></canvas><div id="tip"></div><div id="panel"></div><nav id="crumb"></nav>`;
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 0 });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, get: () => 0 });
    vi.stubGlobal("devicePixelRatio", 1);
    vi.stubGlobal("innerWidth", 880);
    vi.stubGlobal("innerHeight", 700);
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("is drawn again in the new background, with no resize", async () => {
    const slate = build(BUILTIN.starpulse, SLATE).t;
    const lifted = build(BUILTIN.starpulse, { ...SLATE, bg0: SLATE.bg1, bg1: SLATE.stack }).t;
    applyTheme(slate);
    const { renderer } = await import("./renderer");
    const cv = document.getElementById("c") as HTMLCanvasElement;
    const washes = stubContext(cv);
    const r = renderer(cv, new HudStore(), { tip: document.getElementById("tip")!, panel: document.getElementById("panel")! }, false);
    r.start();
    await vi.advanceTimersByTimeAsync(2000);
    expect(washes.at(-1)).toEqual([slate.bg1, slate.bg0]);

    applyTheme(lifted);
    await vi.advanceTimersByTimeAsync(2000);
    expect(washes.at(-1)).toEqual([lifted.bg1, lifted.bg0]);

    applyTheme(slate);
    await vi.advanceTimersByTimeAsync(2000);
    expect(washes.at(-1)).toEqual([slate.bg1, slate.bg0]);
    r.stop();
  });
});
