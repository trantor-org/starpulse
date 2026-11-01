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

// the calls of the mocks, in the order the renders made them: the modal's body, the board's layout and the board's cards
const drawn: string[] = [];
vi.mock("./start", async (actual) => {
  const start = await actual<typeof import("./start")>();
  return { ...start, startLane: vi.fn((...a: Parameters<typeof start.startLane>) => (drawn.push("card"), start.startLane(...a))) };
});
vi.mock("./kanbanModel", async (actual) => {
  const model = await actual<typeof import("./kanbanModel")>();
  return { ...model, layout: vi.fn((...a: Parameters<typeof model.layout>) => (drawn.push("layout"), model.layout(...a))) };
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

  it("lays the board out only after the modal's first draw", () => {
    mount("?view=kanban&task=TASK-1");
    expect(drawn.indexOf("layout")).toBeGreaterThan(drawn.indexOf("modal"));
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

  const record = { title: "An older task", status: "Done", profile: "", priority: "", labels: [], milestone: "m-1", dependencies: [], description: "", plan: "", notes: "", acceptanceCriteria: [], definitionOfDone: [] };
  const answering = async (answer: object | null) => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ record: answer }) })));
    mount("?view=kanban&task=TASK-9");
    await act(async () => { await new Promise((done) => setTimeout(done)); });
  };

  it("opens a Done task the snapshot leaves out from its record, and draws it no card", async () => {
    await answering(record);
    expect(host.querySelector(".mh")?.textContent).toContain("An older task");
    expect(host.querySelectorAll("#cols .card").length).toBe(3);
  });

  it("opens nothing for an id the board has no record of", async () => {
    await answering(null);
    expect(host.querySelector(".mh")).toBeNull();
  });

  it("opens nothing for a record off the board that is not Done", async () => {
    await answering({ ...record, status: "Ready" });
    expect(host.querySelector(".mh")).toBeNull();
  });
});
