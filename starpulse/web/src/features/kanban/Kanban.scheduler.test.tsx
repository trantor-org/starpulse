// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";
import type { TaskRecord } from "./taskViewModel";

const card = (id: string): KanbanTask => ({
  id, title: `title ${id}`, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
});
const hud = { cards: [card("TASK-1"), card("TASK-2")], names: {}, claims: {}, boardUrl: null, hint: "found", capabilities: { create: true } } as unknown as HudState;
const record: TaskRecord = {
  title: "title TASK-1", profile: "", priority: "High", labels: [], milestone: "", dependencies: [], description: "", plan: "", notes: "the full record's notes",
  acceptanceCriteria: [], definitionOfDone: [], session: "",
};

let host: HTMLDivElement, root: Root, fetched: string[];
const settle = () => act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  fetched = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    fetched.push(url);
    return new Response(JSON.stringify({ record }));
  }));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} />));
  await settle();
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the Kanban toolbar, with scheduler moved to Admin", () => {
  it("draws no scheduler strip: the task count sits left of the New task slot in the filters row's right-hand group", () => {
    const group = host.querySelector("#kb .rt")!;

    expect([...group.children].map((c) => c.className.split(" ")[0])).toEqual(["shown", "nt"]);
    expect(group.querySelector(".shown")?.textContent).toBe("2 of 2 tasks");
    expect(host.querySelector('[aria-label="Autopilot"], .ap, .nx')).toBeNull();
  });

  it("keeps Connect a tracker off the filters row, which lives on the Admin view", () => {
    expect(host.textContent).not.toContain("Connect a tracker");
    expect(host.querySelector(".trackerw")).toBeNull();
  });

  it("reads no /api/scheduler", () => {
    expect(fetched).not.toContain("/api/scheduler");
  });
});
