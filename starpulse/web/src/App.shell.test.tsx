// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BOARD_DRAWN } from "./shared/boardDrawn";
import type { HudStore } from "./render/hud";
import type { KanbanTask } from "./features/kanban/kanbanModel";

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
  it("tells a first-time user how to create a task when the board is empty", () => {
    act(() => root.render(<App />));
    act(() => held.store!.set({ tree: { states: ["To Do", "In Progress", "Done"], subs: {}, children: {} }, capabilities: { edit: true, archive: true, create: true } }));
    frame();

    const hint = host.querySelector('[aria-label="Get started"]')?.textContent ?? "";
    expect(hint).toContain("uvx starpulse task create");
    expect(hint).toContain("agent"); // an agent usually drives the CLI, and a person may: by hand, or the Kanban's New task
    expect(hint).toContain("you can too");
    expect(hint).toContain("New task");
  });

  it("offers no create command on an empty board that cannot create a task", () => {
    act(() => root.render(<App />));
    // a Backlog.md or Jira board: `task create` is refused and the Kanban draws no New task
    act(() => held.store!.set({ tree: { states: ["To Do", "In Progress", "Done"], subs: {}, children: {} }, capabilities: { edit: true, archive: true, create: false } }));
    frame();

    expect(mounted('[aria-label="Get started"]')).toBe(false);
  });

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

  it("counts on the Kanban entry only the cards the Kanban draws, not the Done ones from before today", () => {
    const now = Date.now() / 1000;
    const card = (id: string, lane: string, entered: number) => ({ id, lane, entered }) as unknown as KanbanTask;
    act(() => root.render(<App />));
    act(() => held.store!.set({
      tree: { states: ["ready"], subs: {}, children: {} },
      cards: [card("T-1", "ready", now), card("T-2", "done", now), card("T-3", "done", now - 3 * 86400), card("T-4", "done", now - 9 * 86400)],
    }));
    frame();

    expect(host.querySelector('#nav [title="Kanban"] .n')?.textContent).toBe("2");
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
