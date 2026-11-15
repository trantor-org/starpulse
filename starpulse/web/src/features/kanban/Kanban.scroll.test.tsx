// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore, startLane } from "./start";

// every card asks startLane while it draws, so its calls count the cards a render drew
vi.mock("./start", async (actual) => {
  const start = await actual<typeof import("./start")>();
  return { ...start, startLane: vi.fn(start.startLane) };
});

const card = (id: string, title = `title ${id}`): KanbanTask => ({
  id, title, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
});
const hud = { cards: [card("TASK-1"), card("TASK-2"), card("TASK-3")], names: {}, roles: LIFECYCLE_ROLES, claims: {}, settled: [], boardUrl: null, stats: "live · 10:00 MST", dags: ["a"], pools: [], feed: [] } as unknown as HudState;

let host: HTMLDivElement, root: Root;
const moves = new MoveStore(async () => ({ ok: true }) as never);
const starts = new StartStore((async () => ({})) as never, moves);
const noop = () => {};
const show = (h: HudState, spot: string | null = null) =>
  act(() => root.render(<Kanban hud={h} moves={moves} starts={starts} compact={false} constellation={noop} searchSlot={null} outlineSlot={null} spot={spot} />));
const drawn = () => vi.mocked(startLane).mock.calls.length;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  show(hud);
  vi.mocked(startLane).mockClear();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("a column while it scrolls", () => {
  it("takes its cards out of hit-testing until the scroll rests, drawing no card, so cards passing under a still pointer light, read and pre-draw nothing", () => {
    vi.useFakeTimers();
    try {
      const column = host.querySelector<HTMLElement>('#cols .col[data-lane="ready"] .body')!;
      act(() => void column.dispatchEvent(new Event("scroll")));
      expect(column.classList.contains("scrolling")).toBe(true);

      act(() => void vi.advanceTimersByTime(200));
      act(() => void column.dispatchEvent(new Event("scroll")));
      act(() => void vi.advanceTimersByTime(200));
      expect(column.classList.contains("scrolling")).toBe(true);

      act(() => void vi.advanceTimersByTime(200));
      expect(column.classList.contains("scrolling")).toBe(false);
      expect(drawn()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("a spotted card", () => {
  it("scrolls into view when spotted, and keeps the operator's scroll across a task change", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    show(hud, "TASK-2");
    expect(scroll).toHaveBeenCalledTimes(1);

    show({ ...hud, cards: [card("TASK-1", "renamed"), ...hud.cards.slice(1)] } as HudState, "TASK-2");
    expect(scroll).toHaveBeenCalledTimes(1);

    show(hud, "TASK-3");
    expect(scroll).toHaveBeenCalledTimes(2);
  });

  it("scrolls once when the spotted card reaches the board after the spot was set", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const without = { ...hud, cards: hud.cards.slice(0, 2) } as HudState;
    show(without, "TASK-3");
    expect(scroll).not.toHaveBeenCalled();

    show(hud, "TASK-3");
    expect(scroll).toHaveBeenCalledTimes(1);
  });
});
