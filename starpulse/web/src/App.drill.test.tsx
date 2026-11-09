// @vitest-environment jsdom
// The In Progress sun opens the Suns lenses drill-in: the renderer refuses the machine ledger level for it and asks the page to drill into the first working task instead.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { KanbanTask } from "./features/kanban/kanbanModel";
import type { HudStore } from "./render/hud";
import { BOARD, type Path } from "./render/levels";

// the canvas renderer needs a browser's 2D context; this one hands the test the store the page reads and the drill the page registers, and hands a drill the renderer held before registration over on it, as the renderer does
const held = vi.hoisted(() => ({ store: undefined as HudStore | undefined, drill: null as null | ((task: string) => void), early: null as string | null, calls: [] as [string, unknown[]][] }));
vi.mock("./render/renderer", async (original) => ({
  ...(await original<typeof import("./render/renderer")>()),
  renderer: (_canvas: HTMLCanvasElement, store: HudStore) => {
    held.store = store;
    return new Proxy({}, { get: (_, k) => (k === "onDrill" ? (fn: typeof held.drill) => { held.drill = fn; if (fn && held.early) fn(held.early); } : (...a: unknown[]) => void held.calls.push([String(k), a])) });
  },
}));
vi.mock("./lazyViews", async (original) => ({ ...(await original<typeof import("./lazyViews")>()), prefetchViews: () => () => {} }));

let host: HTMLDivElement, root: Root, frames: FrameRequestCallback[];
const drillIn = '[aria-label="In Progress drill-in"]';
const card = (id: string, lane: string) => ({ id, title: id, lane, dependencies: [] }) as unknown as KanbanTask;
const lane = (id: string): Path => [...BOARD, { kind: "state", id }];
/** The renderer asking the page to drill into a task; it opens the drill-in, so it runs inside `act`. */
const drills = (id: string) => act(() => held.drill!(id));
/** Hands the page a board and runs the frame that marks it drawn, so the Navigator draws its body. */
const board = (cards: KanbanTask[]) => {
  act(() => held.store!.set({ tree: { states: ["Ready", "In Progress"], subs: {}, children: {} }, roles: { working: "In Progress" }, cards }));
  act(() => frames.splice(0).forEach((f) => f(0)));
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  frames = [];
  held.drill = null;
  held.early = null;
  held.calls = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
const mount = () => act(() => root.render(<App />));
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.className = "";
  vi.unstubAllGlobals();
});

describe("the In Progress sun", () => {
  beforeEach(() => mount());

  it("opens the Suns drill-in on the task the renderer names, and puts the task in the address", async () => {
    board([card("TASK-1", "Ready"), card("TASK-2", "In Progress"), card("TASK-3", "In Progress")]);

    drills("TASK-2");
    await act(async () => void (await import("./features/level/SunsDrillIn")));

    expect(host.querySelector(`#nav nav[aria-label="In Progress tasks"] button`)?.getAttribute("aria-label")).toMatch(/^TASK-2 /);
    expect(location.search).toContain("drill=TASK-2");
  });

  it("makes the Navigator the In Progress task list while the drill-in is open, in place of the Leaderboard, and gives it back on close", async () => {
    board([card("TASK-2", "In Progress"), card("TASK-3", "In Progress")]);
    drills("TASK-2");
    await act(async () => void (await import("./features/level/SunsDrillIn")));

    expect([...host.querySelectorAll('#nav nav[aria-label="In Progress tasks"] button')].map((b) => b.getAttribute("aria-label")?.split(" ")[0])).toEqual(["TASK-2", "TASK-3"]);
    expect(host.querySelector("#nav .leaderboard")).toBeNull();

    act(() => host.querySelector<HTMLButtonElement>('button[aria-label="Back to the Board"]')!.click());
    expect(host.querySelector(drillIn)).toBeNull();
    expect(host.querySelector("#nav .leaderboard")).not.toBeNull();
  });

  it("opens the drill-in before the HUD cards fill, with the lane still empty on the page", async () => {
    board([]);

    drills("TASK-7");
    await act(async () => void (await import("./features/level/SunsDrillIn")));

    expect(location.search).toContain("drill=TASK-7");
    expect(host.querySelector(drillIn)).not.toBeNull();
  });

  it("the Star Map in the side panel closes the drill-in and starts the Star Map at the Board's top level, from any view and depth", async () => {
    board([card("TASK-2", "In Progress")]);
    act(() => held.store!.set({ path: lane("Review") }));
    drills("TASK-2");
    await act(async () => void (await import("./features/level/SunsDrillIn")));
    const starMap = () => host.querySelector<HTMLButtonElement>('#nav .views button[title="Star Map"]')!;

    act(() => starMap().click());
    expect(host.querySelector(drillIn)).toBeNull();
    expect(location.search).not.toContain("drill=");
    expect(held.calls.filter(([k]) => k === "go").at(-1)?.[1][0]).toEqual(BOARD);

    held.calls = [];
    act(() => host.querySelector<HTMLButtonElement>('#nav .views button[title="Kanban"]')?.click());
    act(() => starMap().click());
    expect(held.calls.filter(([k]) => k === "go").at(-1)?.[1][0]).toEqual(BOARD);
  });
});

describe("a drill the renderer asked for before the page registered", () => {
  it("opens once the page registers, before the first snapshot's cards reach it", async () => {
    held.early = "TASK-5";
    mount();
    await act(async () => void (await import("./features/level/SunsDrillIn")));

    expect(location.search).toContain("drill=TASK-5");
    expect(host.querySelector(drillIn)).not.toBeNull();
  });
});
