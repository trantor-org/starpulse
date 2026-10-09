// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import type { KanbanTask } from "./kanban";
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
const hud = { cards: [card("TASK-1"), card("TASK-2"), card("TASK-3")], names: {}, claims: {}, settled: [], boardUrl: null, stats: "live · 10:00 MST", dags: ["a"], pools: [], feed: [] } as unknown as HudState;

let host: HTMLDivElement, root: Root;
const moves = new MoveStore(async () => ({ ok: true }) as never);
const starts = new StartStore((async () => ({})) as never, moves);
const noop = () => {};
const show = (h: HudState) =>
  act(() => root.render(<Kanban hud={h} moves={moves} starts={starts} compact={false} constellation={noop} searchSlot={null} outlineSlot={null} />));
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

describe("a stream event that changes no card the board shows", () => {
  it("draws no card again", () => {
    // a dags event rewrites the clock, the DAG names and the feed, which the Kanban never shows
    show({ ...hud, stats: "live · 10:01 MST", dags: ["a", "b"], feed: [{ key: "k" }] } as unknown as HudState);

    expect(drawn()).toBe(0);
  });

  it("still draws the card that changes, and only that one", () => {
    show({ ...hud, cards: [card("TASK-1", "renamed"), ...hud.cards.slice(1)] });

    expect(drawn()).toBe(1);
    expect(host.querySelector('#cols .card[data-id="TASK-1"]')?.textContent).toContain("renamed");
  });
});
