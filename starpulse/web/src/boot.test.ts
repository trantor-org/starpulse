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

  it("reads the record of a task the address names at boot, before the renderer's snapshot or any React fetch", async () => {
    history.replaceState(null, "", "/?view=kanban&task=TASK-9");
    const asked: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => { asked.push(url); return new Response(JSON.stringify({ record: { id: "TASK-9" } })); }));
    const { boot } = await import("./boot");
    const started = made.calls.length;

    const held = boot(vi.fn());

    expect(made.calls.length).toBe(started + 1);
    expect(asked).toEqual(["/api/task/TASK-9"]);
    expect(held.records.fresh("TASK-9")).toBeDefined();
  });

  it("adopts the record read the page's head started, instead of asking for it again", async () => {
    history.replaceState(null, "", "/?view=kanban&task=TASK-9");
    const fetched = vi.fn();
    vi.stubGlobal("fetch", fetched);
    vi.stubGlobal("__earlyRecord", { id: "TASK-9", read: Promise.resolve(new Response(JSON.stringify({ record: { title: "early" } }))) });
    const { boot } = await import("./boot");

    const held = boot(vi.fn());

    expect(await held.records.fresh("TASK-9")!.read).toEqual({ title: "early" });
    expect(fetched).not.toHaveBeenCalled();
  });

  it("reads no record when the address names no task", async () => {
    const fetched = vi.fn();
    vi.stubGlobal("fetch", fetched);
    const { boot } = await import("./boot");

    boot(vi.fn());

    expect(fetched).not.toHaveBeenCalled();
  });

  it("marks in the frame the renderer first draws, then mounts the page a frame behind it", async () => {
    const mount = vi.fn();
    const { boot } = await import("./boot");
    boot(mount);
    const onDrawn = made.calls[0][5] as () => void;

    onDrawn();
    expect(marked()).toBe(true);
    expect(mount).not.toHaveBeenCalled();

    frame();

    expect(mount).toHaveBeenCalledTimes(1);
  });

  it("mounts the page when no board arrives, so a stream that never answers still shows its status", async () => {
    vi.useFakeTimers();
    const mount = vi.fn(), preload = vi.fn();
    const { boot } = await import("./boot");
    boot(mount, preload);

    vi.advanceTimersByTime(2000);

    expect(preload, "the Star Map is the Board's own frame, so no view loads ahead").not.toHaveBeenCalled();
    expect(mount).toHaveBeenCalledTimes(1);
    expect(marked()).toBe(false);
  });

  it("hides the Star Map at once when the page opens on another view, mounts that view without waiting for the board, and marks when the board arrives", async () => {
    history.replaceState(null, "", "/?view=kanban");
    const mount = vi.fn(), preload = vi.fn();
    const { boot } = await import("./boot");
    boot(mount, preload);

    expect(preload, "the view's own chunk is asked for now, not once the page's first render reaches it").toHaveBeenCalledExactlyOnceWith("kanban");
    expect(made.calls[0][5]).toBeUndefined();
    expect(document.getElementById("c")!.classList.contains("off")).toBe(true);
    expect(document.getElementById("crumb")!.classList.contains("off")).toBe(true);
    expect(made.spy.show).toHaveBeenCalledWith(false);
    expect(mount, "the view's chunks load beside the snapshot, not behind it").toHaveBeenCalledTimes(1);
    expect(marked()).toBe(false);

    (await hud()).set({ tree: { states: ["ready"], subs: {}, children: {} } });
    frame();

    expect(marked()).toBe(true);
    expect(mount).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["an address naming it", () => history.replaceState(null, "", "/?view=constellation")],
    ["a saved Opens on", () => { history.replaceState(null, "", "/"); localStorage.setItem("fv.admin.prefs", JSON.stringify({ view: "constellation" })); }],
  ])("draws no Star Map at phone width for %s, and hides it until the page widens", async (_name, address) => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(max-width: 900px)" }));
    address();
    const { boot } = await import("./boot");
    boot(vi.fn());

    expect(made.calls[0][5], "no first-frame mark waits on the Star Map").toBeUndefined();
    expect(document.getElementById("c")!.classList.contains("off")).toBe(true);
    expect(made.spy.show).toHaveBeenCalledWith(false);
  });

  it("holds what the page adopts: the store, the Admin's preferences and the renderer", async () => {
    const { boot, booted } = await import("./boot");
    expect(booted()).toBeNull();
    const held = boot(vi.fn());

    expect(booted()).toBe(held);
    expect(held.renderer).toBe(made.spy);
  });
});
