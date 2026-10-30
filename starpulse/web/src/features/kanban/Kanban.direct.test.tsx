// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";

// the calls of the two mocks, in the order the renders made them: the modal's body and the board's cards
const drawn: string[] = [];
vi.mock("./start", async (actual) => {
  const start = await actual<typeof import("./start")>();
  return { ...start, startLane: vi.fn((...a: Parameters<typeof start.startLane>) => (drawn.push("card"), start.startLane(...a))) };
});
vi.mock("./TaskView", async (actual) => {
  const view = await actual<typeof import("./TaskView")>();
  return { ...view, TaskView: vi.fn((...a: Parameters<typeof view.TaskView>) => (drawn.push("modal"), view.TaskView(...a))) };
});

const card = (id: string): KanbanTask => ({
  id, title: `title ${id}`, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, machines: [], moves: {}, entered: 0, created: null, workableSince: null,
} as unknown as KanbanTask);
const hud = { cards: [card("TASK-1"), card("TASK-2"), card("TASK-3")], names: {}, roles: LIFECYCLE_ROLES, claims: {}, boardUrl: null } as unknown as HudState;

let host: HTMLDivElement, root: Root;
const mount = (search: string) => {
  history.replaceState(null, "", `/${search}`);
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} />));
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  drawn.length = 0;
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ record: null }) })));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("a Kanban opened on a direct task link", () => {
  it("draws the linked task's modal before any card of the board", () => {
    mount("?view=kanban&task=TASK-1");
    expect(drawn.indexOf("modal")).toBeGreaterThanOrEqual(0);
    expect(drawn.indexOf("card")).toBeGreaterThan(drawn.indexOf("modal"));
  });

  it("still draws the whole board behind the modal", () => {
    mount("?view=kanban&task=TASK-1");
    expect(host.querySelectorAll("#cols .card").length).toBe(3);
  });

  it("draws the board's cards at once when the address names no task", () => {
    mount("?view=kanban");
    expect(drawn).not.toContain("modal");
    expect(drawn.includes("card")).toBe(true);
  });
});
