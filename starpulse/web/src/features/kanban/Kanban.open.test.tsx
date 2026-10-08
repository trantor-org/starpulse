// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore, startLane } from "./start";
import type { TaskRecord } from "./taskView";

// every card asks startLane while it draws, so its calls count the cards a render drew
vi.mock("./start", async (actual) => {
  const start = await actual<typeof import("./start")>();
  return { ...start, startLane: vi.fn(start.startLane) };
});

const card = (id: string): KanbanTask => ({
  id, title: `title ${id}`, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
});
const hud = { cards: [card("TASK-1"), card("TASK-2"), card("TASK-3")], names: {}, claims: {}, boardUrl: null } as unknown as HudState;
const record: TaskRecord = {
  title: "title TASK-1", profile: "", priority: "High", labels: [], milestone: "", dependencies: [], description: "", plan: "1. Write the test", notes: "the full record's notes",
  acceptanceCriteria: [], definitionOfDone: [], session: "",
};

let host: HTMLDivElement, root: Root, fetched: string[];
const cardOf = (id: string) => host.querySelector<HTMLElement>(`#cols .card[data-id="${id}"]`)!;
const dialog = () => document.querySelector<HTMLElement>("[role=dialog]");
const settle = () => act(async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); });
const hover = (el: HTMLElement) => act(() => void el.dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  fetched = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    fetched.push(url);
    return { ok: true, json: async () => ({ record }) };
  }));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("opening a task's modal", () => {
  it("reads the record while the pointer rests on the card, so the click draws the full record without another request", async () => {
    hover(cardOf("TASK-1"));
    await settle();
    expect(fetched).toEqual(["/api/task/TASK-1"]);

    act(() => cardOf("TASK-1").click());

    expect(dialog()?.textContent).toContain("the full record's notes");
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    await settle();
    expect(fetched).toEqual(["/api/task/TASK-1"]);
  });

  it("marks the modal busy until a record no hover read ahead arrives", async () => {
    act(() => cardOf("TASK-2").click());

    expect(dialog()?.getAttribute("aria-busy")).toBe("true");
    await settle();
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    expect(fetched).toEqual(["/api/task/TASK-2"]);
  });

  it("leaves the board's cards undrawn as the modal opens and closes", async () => {
    // the clock's catch-up tick after mount redraws the board on its own; let it pass before counting
    await act(async () => { await new Promise((r) => setTimeout(r, 0)); });
    vi.mocked(startLane).mockClear();

    act(() => cardOf("TASK-1").click());
    await settle();
    act(() => void document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));

    expect(dialog()).toBeNull();
    const redrawn = vi.mocked(startLane).mock.calls.map(([t]) => t.id).filter((id) => id !== "TASK-1");
    expect(redrawn).toEqual([]);
  });
});
