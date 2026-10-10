// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";
import type { TaskRecord } from "./taskView";

const card = (id: string): KanbanTask => ({
  id, title: `title ${id}`, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
});
const hud = { cards: [card("TASK-1"), card("TASK-2")], names: {}, claims: {}, boardUrl: null, hint: "found", capabilities: { create: true } } as unknown as HudState;
const record: TaskRecord = {
  title: "title TASK-1", profile: "", priority: "High", labels: [], milestone: "", dependencies: [], description: "", plan: "", notes: "the full record's notes",
  acceptanceCriteria: [], definitionOfDone: [], session: "",
};
const STATUS = {
  enabled: true,
  sampledAt: 1,
  dimensions: [{ name: "cpu", use: 41, limit: 80 }, { name: "sessions", use: 1, limit: 4 }],
  inFlight: [],
  next: { task: "TASK-1", title: "title TASK-1", verdict: "starting", reason: "" },
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
    return new Response(JSON.stringify(url === "/api/autopilot" ? STATUS : { record }));
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

describe("the Kanban's autopilot strip", () => {
  it("sits directly left of the task count, which sits left of the New task slot, in the filters row's right-hand group", () => {
    const group = host.querySelector("#kb .rt")!;

    expect([...group.children].map((c) => c.className.split(" ")[0])).toEqual(["ap", "shown", "nt"]);
    expect(group.querySelector(".shown")?.textContent).toBe("2 of 2 tasks");
    expect(group.querySelector(".nt")?.textContent).toContain("New task");
  });

  it("replaces Connect a tracker in the filters row, which lives on the Admin view now", () => {
    expect(host.textContent).not.toContain("Connect a tracker");
    expect(host.querySelector(".trackerw")).toBeNull();
  });

  it("reads /api/autopilot once the board draws and names the pick", () => {
    expect(fetched).toContain("/api/autopilot");
    expect(host.querySelector("button.nx")?.textContent).toBe("Next TASK-1");
  });

  it("opens the pick's task modal from the strip", async () => {
    act(() => host.querySelector<HTMLButtonElement>("button.nx")!.click());
    await settle();

    expect(document.querySelector("[role=dialog]")).not.toBeNull();
    expect(fetched).toContain("/api/task/TASK-1");
  });
});
