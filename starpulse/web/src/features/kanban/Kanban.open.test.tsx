// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore, startLane } from "./start";
import { TaskView } from "./TaskView";
import { PRE_DRAW_REST_MS, RecordCache, type TaskRecord } from "./taskView";

// every card asks startLane while it draws, so its calls count the cards a render drew
vi.mock("./start", async (actual) => {
  const start = await actual<typeof import("./start")>();
  return { ...start, startLane: vi.fn(start.startLane) };
});

// every modal body drawn calls TaskView, so its calls count the times the modal's tree was drawn
vi.mock("./TaskView", async (actual) => {
  const view = await actual<typeof import("./TaskView")>();
  return { ...view, TaskView: vi.fn(view.TaskView) };
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
const leave = (el: HTMLElement) => act(() => void el.dispatchEvent(new MouseEvent("pointerout", { bubbles: true, relatedTarget: document.body })));
const rest = () => act(async () => { await new Promise((r) => setTimeout(r, PRE_DRAW_REST_MS + 20)); for (let i = 0; i < 5; i++) await Promise.resolve(); });

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
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-1"]);

    act(() => cardOf("TASK-1").click());

    expect(dialog()?.textContent).toContain("the full record's notes");
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    await settle();
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-1"]);
  });

  it("marks the modal busy until a record no hover read ahead arrives", async () => {
    act(() => cardOf("TASK-2").click());

    expect(dialog()?.getAttribute("aria-busy")).toBe("true");
    await settle();
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-2"]);
  });

  it("draws a record that landed after the modal rendered but before its effect ran, instead of staying busy for good", async () => {
    // the read ahead lands between the modal's render (which saw no record) and its effect (which sees one): a click or a
    // pre-draw under load puts a macrotask between the two
    const rendered = vi.mocked(TaskView).mock.calls.length;
    const fresh = vi.spyOn(RecordCache.prototype, "fresh").mockImplementation(() => ({
      at: Date.now(),
      read: Promise.resolve(record),
      get got() { return vi.mocked(TaskView).mock.calls.length > rendered ? record : undefined; },
    }));
    try {
      act(() => cardOf("TASK-2").click());
      await settle();

      expect(dialog()?.getAttribute("aria-busy")).toBe("false");
      expect(dialog()?.textContent).toContain("the full record's notes");
    } finally {
      fresh.mockRestore();
    }
  });

  it("shows a failed record read, with a retry that draws the record, instead of staying busy", async () => {
    vi.mocked(fetch).mockImplementationOnce(async (url) => { fetched.push(String(url)); throw new TypeError("network"); });
    act(() => cardOf("TASK-2").click());
    await settle();

    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    expect(dialog()?.querySelector("[role=alert]")?.textContent).toContain("could not be read");
    expect(dialog()?.textContent).not.toContain("the full record's notes");

    act(() => dialog()!.querySelector<HTMLButtonElement>("[role=alert] button")!.click());
    expect(dialog()?.getAttribute("aria-busy")).toBe("true");
    await settle();
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    expect(dialog()?.querySelector("[role=alert]")).toBeNull();
    expect(dialog()?.textContent).toContain("the full record's notes");
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-2", "/api/task/TASK-2"]);
  });

  it("reads the record again when the read ahead of the click failed, rather than showing that failure", async () => {
    vi.mocked(fetch).mockImplementationOnce(async (url) => { fetched.push(String(url)); throw new TypeError("network"); });
    hover(cardOf("TASK-1"));
    await rest();
    act(() => cardOf("TASK-1").click());
    await settle();

    expect(dialog()?.querySelector("[role=alert]")).toBeNull();
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    expect(dialog()?.textContent).toContain("the full record's notes");
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-1", "/api/task/TASK-1"]);
  });

  it("reads the record again when the read ahead fails after the modal was drawn ahead, rather than showing that failure", async () => {
    let fail: (e: unknown) => void = () => {};
    vi.mocked(fetch).mockImplementationOnce((url) => {
      fetched.push(String(url));
      return new Promise((_, reject) => { fail = reject; });
    });
    hover(cardOf("TASK-1"));
    await rest();
    expect(dialog()?.getAttribute("aria-busy")).toBe("true");
    await act(async () => { fail(new TypeError("network")); });
    await settle();
    act(() => cardOf("TASK-1").click());
    await settle();

    expect(dialog()?.querySelector("[role=alert]")).toBeNull();
    expect(dialog()?.getAttribute("aria-busy")).toBe("false");
    expect(dialog()?.textContent).toContain("the full record's notes");
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-1", "/api/task/TASK-1"]);
  });

  it("draws a rested card's modal hidden and inert, so the click shows that same dialog instead of building one", async () => {
    hover(cardOf("TASK-1"));
    await rest();

    const drawn = dialog();
    expect(drawn).not.toBeNull();
    expect(drawn?.closest("[inert]")).not.toBeNull();
    expect(drawn?.getAttribute("aria-busy")).toBe("false");
    act(() => void document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(dialog()).toBe(drawn);

    act(() => cardOf("TASK-1").click());

    expect(dialog()).toBe(drawn);
    expect(drawn?.closest("[inert]")).toBeNull();
    expect(drawn?.textContent).toContain("the full record's notes");
  });

  it("shows the modal drawn ahead without drawing its tree again, at the click or after it", async () => {
    hover(cardOf("TASK-1"));
    await rest();
    expect(dialog()).not.toBeNull();
    vi.mocked(TaskView).mockClear();

    act(() => cardOf("TASK-1").click());
    expect(TaskView).not.toHaveBeenCalled();
    await rest();
    expect(TaskView).not.toHaveBeenCalled();
  });

  it("draws a rested card's modal before its record lands, and fills it when the record lands after the click", async () => {
    let land: (v: unknown) => void = () => {};
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      fetched.push(url);
      return new Promise((resolve) => { land = resolve; });
    }));
    hover(cardOf("TASK-1"));
    await rest();

    const drawn = dialog();
    expect(drawn?.closest("[inert]")).not.toBeNull();
    expect(drawn?.getAttribute("aria-busy")).toBe("true");
    act(() => cardOf("TASK-1").click());
    expect(dialog()).toBe(drawn);

    await act(async () => { land({ ok: true, json: async () => ({ record }) }); for (let i = 0; i < 5; i++) await Promise.resolve(); });
    expect(drawn?.getAttribute("aria-busy")).toBe("false");
    expect(drawn?.textContent).toContain("the full record's notes");
    expect(fetched).toEqual(["/api/autopilot", "/api/task/TASK-1"]);
  });

  it("draws no modal for a pointer that passes over a card without resting, and drops the hidden one when the pointer leaves", async () => {
    hover(cardOf("TASK-1"));
    leave(cardOf("TASK-1"));
    await rest();
    expect(dialog()).toBeNull();

    hover(cardOf("TASK-2"));
    await rest();
    expect(dialog()).not.toBeNull();
    leave(cardOf("TASK-2"));
    await settle();
    expect(dialog()).toBeNull();
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
