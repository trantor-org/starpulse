// @vitest-environment jsdom
// The In Progress sun opens the Suns lenses drill-in: the page vetoes the machine ledger level for it and shows the first working task instead.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { KanbanTask } from "./features/kanban/kanbanModel";
import type { HudStore } from "./render/hud";
import { BOARD, type Path } from "./render/levels";

// the canvas renderer needs a browser's 2D context; this one hands the test the store the page reads and the veto the page installs
const held = vi.hoisted(() => ({ store: undefined as HudStore | undefined, veto: null as null | ((p: Path) => boolean) }));
vi.mock("./render/renderer", async (original) => ({
  ...(await original<typeof import("./render/renderer")>()),
  renderer: (_canvas: HTMLCanvasElement, store: HudStore) => {
    held.store = store;
    return new Proxy({}, { get: (_, k) => (k === "intercept" ? (fn: typeof held.veto) => void (held.veto = fn) : () => undefined) });
  },
}));
vi.mock("./lazyViews", async (original) => ({ ...(await original<typeof import("./lazyViews")>()), prefetchViews: () => () => {} }));

let host: HTMLDivElement, root: Root, frames: FrameRequestCallback[];
const drillIn = '[aria-label="In Progress drill-in"]';
const card = (id: string, lane: string) => ({ id, title: id, lane, dependencies: [] }) as unknown as KanbanTask;
const lane = (id: string): Path => [...BOARD, { kind: "state", id }];
/** The veto's answer for a path the renderer is asked to open; it opens the drill-in, so it runs inside `act`. */
const vetoes = (p: Path) => {
  let answer: boolean | undefined;
  act(() => void (answer = held.veto!(p)));
  return answer;
};
/** Hands the page a board and runs the frame that marks it drawn, so the Navigator draws its body. */
const board = (cards: KanbanTask[]) => {
  act(() => held.store!.set({ tree: { states: ["Ready", "In Progress"], subs: {}, children: {} }, roles: { working: "In Progress" }, cards }));
  act(() => frames.splice(0).forEach((f) => f(0)));
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  frames = [];
  held.veto = null;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  act(() => root.render(<App />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.className = "";
  vi.unstubAllGlobals();
});

describe("the In Progress sun", () => {
  it("opens the Suns drill-in on the first working task instead of the machine ledger, and puts the task in the address", async () => {
    board([card("TASK-1", "Ready"), card("TASK-2", "In Progress"), card("TASK-3", "In Progress")]);

    expect(vetoes(lane("In Progress"))).toBe(true);
    await act(async () => void (await import("./features/level/SunsDrillIn")));

    expect(host.querySelector(`#nav nav[aria-label="In Progress tasks"] button`)?.getAttribute("aria-label")).toMatch(/^TASK-2 /);
    expect(location.search).toContain("drill=TASK-2");
  });

  it("makes the Navigator the In Progress task list while the drill-in is open, in place of the Leaderboard, and gives it back on close", async () => {
    board([card("TASK-2", "In Progress"), card("TASK-3", "In Progress")]);
    vetoes(lane("In Progress"));
    await act(async () => void (await import("./features/level/SunsDrillIn")));

    expect([...host.querySelectorAll('#nav nav[aria-label="In Progress tasks"] button')].map((b) => b.getAttribute("aria-label")?.split(" ")[0])).toEqual(["TASK-2", "TASK-3"]);
    expect(host.querySelector("#nav .leaderboard")).toBeNull();

    act(() => host.querySelector<HTMLButtonElement>('button[aria-label="Back to the Board"]')!.click());
    expect(host.querySelector(drillIn)).toBeNull();
    expect(host.querySelector("#nav .leaderboard")).not.toBeNull();
  });

  it("vetoes only the In Progress level: other lanes and the machines under it open as before", () => {
    board([card("TASK-2", "In Progress")]);

    expect(vetoes(lane("Ready"))).toBe(false);
    expect(vetoes(BOARD)).toBe(false);
    expect(vetoes([...lane("In Progress"), { kind: "machine", flow: "qa" }])).toBe(false);
    expect(document.querySelector(drillIn)).toBeNull();
  });

  it("keeps the machine ledger where the Suns view does not apply: no task is in progress", () => {
    board([card("TASK-1", "Ready")]);

    expect(vetoes(lane("In Progress"))).toBe(false);
    expect(document.querySelector(drillIn)).toBeNull();
  });
});
