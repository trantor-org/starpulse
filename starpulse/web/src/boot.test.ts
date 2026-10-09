// @vitest-environment jsdom
// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
// @ts-expect-error Same Node-only import: jsdom swaps the global URL for one readFileSync refuses.
import { URL as NodeURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOARD_DRAWN } from "./shared/boardMark";

// the renderer needs a browser's 2D context; this one records how the page started it
const made = vi.hoisted(() => ({ calls: [] as unknown[][], spy: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("./render/renderer", () => ({
  renderer: (...args: unknown[]) => {
    made.calls.push(args);
    made.spy = { start: vi.fn(), stop: vi.fn(), show: vi.fn(), refresh: vi.fn() };
    return made.spy;
  },
}));

const page = readFileSync(new NodeURL("../index.html", import.meta.url), "utf8");
const frames = page.slice(page.indexOf("<body>") + 6, page.indexOf('<script type="module"'));

let rafs: FrameRequestCallback[];
const frame = () => rafs.splice(0).forEach((f) => f(0));
const marked = () => performance.getEntriesByName(BOARD_DRAWN).length > 0;
const hud = async () => (await import("./boot")).booted()!.store;

beforeEach(() => {
  vi.resetModules();
  made.calls.length = 0;
  rafs = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => rafs.push(cb));
  performance.clearMarks(BOARD_DRAWN);
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  document.body.innerHTML = frames;
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the page's boot", () => {
  it("starts the renderer on the frames index.html carries, before any React tree exists", async () => {
    const mount = vi.fn();
    const { boot } = await import("./boot");
    boot(mount);

    const [canvas, , els] = made.calls[0] as [HTMLCanvasElement, unknown, { tip: HTMLElement; panel: HTMLElement }];
    expect(canvas).toBe(document.getElementById("c"));
    expect(els.tip).toBe(document.getElementById("tip"));
    expect(els.panel).toBe(document.getElementById("panel"));
    expect(made.spy.start).toHaveBeenCalledTimes(1);
    expect(mount).not.toHaveBeenCalled();
  });

  it("marks the frame after the renderer's first draw, then mounts the page", async () => {
    const mount = vi.fn();
    const { boot } = await import("./boot");
    boot(mount);
    const onDrawn = made.calls[0][5] as () => void;

    onDrawn();
    expect(marked()).toBe(false);
    expect(mount).not.toHaveBeenCalled();

    frame();

    expect(marked()).toBe(true);
    expect(mount).toHaveBeenCalledTimes(1);
  });

  it("mounts the page when no board arrives, so a stream that never answers still shows its status", async () => {
    vi.useFakeTimers();
    const mount = vi.fn();
    const { boot } = await import("./boot");
    boot(mount);

    vi.advanceTimersByTime(2000);

    expect(mount).toHaveBeenCalledTimes(1);
    expect(marked()).toBe(false);
  });

  it("hides the Star Map at once when the page opens on another view, and marks when that view's board arrives", async () => {
    history.replaceState(null, "", "/?view=kanban");
    const mount = vi.fn();
    const { boot } = await import("./boot");
    boot(mount);

    expect(made.calls[0][5]).toBeUndefined();
    expect(document.getElementById("c")!.classList.contains("off")).toBe(true);
    expect(document.getElementById("crumb")!.classList.contains("off")).toBe(true);
    expect(made.spy.show).toHaveBeenCalledWith(false);

    (await hud()).set({ tree: { states: ["ready"], subs: {}, children: {} } });
    frame();

    expect(marked()).toBe(true);
    expect(mount).toHaveBeenCalledTimes(1);
  });

  it("holds what the page adopts: the store, the Admin's preferences and the renderer", async () => {
    const { boot, booted } = await import("./boot");
    expect(booted()).toBeNull();
    const held = boot(vi.fn());

    expect(booted()).toBe(held);
    expect(held.renderer).toBe(made.spy);
  });
});
