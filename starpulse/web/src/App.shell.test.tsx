// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BOARD_DRAWN } from "./shared/boardDrawn";
import type { HudStore } from "./render/hud";

// the canvas renderer needs a browser's 2D context; this one only hands the test the store the page reads
const held = vi.hoisted(() => ({ store: undefined as HudStore | undefined }));
vi.mock("./render/renderer", async (original) => ({
  ...(await original<typeof import("./render/renderer")>()),
  renderer: (_canvas: HTMLCanvasElement, store: HudStore) => {
    held.store = store;
    return new Proxy({}, { get: () => () => undefined });
  },
}));

let host: HTMLDivElement, root: Root, frames: FrameRequestCallback[];
const mounted = (selector: string) => host.querySelector(selector) !== null;
const frame = () => act(() => void frames.splice(0).forEach((f) => f(0)));
const marked = () => performance.getEntriesByName(BOARD_DRAWN).length > 0;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  performance.clearMarks(BOARD_DRAWN);
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.className = "";
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("the page's first tree", () => {
  it("mounts the navigator and the rail after the board-drawn mark, and keeps their frames so the canvas is sized the same", () => {
    act(() => root.render(<App />));
    act(() => held.store!.set({ tree: { states: ["ready"], subs: {}, children: {} } }));

    // the Board is in the commit, not yet in a frame: its sizing needs the two asides, their contents wait
    expect(mounted("#nav")).toBe(true);
    expect(mounted("#rail")).toBe(true);
    expect(mounted("#nav .views")).toBe(false);
    expect(mounted("#rail #legend")).toBe(false);
    expect(marked()).toBe(false);

    frame();

    expect(marked()).toBe(true);
    expect(mounted("#nav .views")).toBe(true);
    expect(mounted("#rail #legend")).toBe(true);
  });

  it("mounts them anyway when no board arrives, so a stream that never answers still shows its status", () => {
    vi.useFakeTimers();
    act(() => root.render(<App />));
    expect(mounted("#nav .views")).toBe(false);

    act(() => void vi.advanceTimersByTime(2000));

    expect(mounted("#nav .views")).toBe(true);
    expect(mounted("#rail #legend")).toBe(true);
  });
});
