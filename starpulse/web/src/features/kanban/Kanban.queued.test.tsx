// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const NOW = Date.now() / 1000;
const run = (status: string) => ({ url: "https://dagu/runs/1", status, startedAt: "2026-10-29T17:00:00Z" });
const card = (id: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: id, lane: "ready", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
  live: { machine: "lifecycle", state: "ready", at: NOW - 600 }, ...extra,
});

let host: HTMLDivElement, root: Root;
const mount = (cards: KanbanTask[]) => {
  const hud = { cards, names: {}, roles: LIFECYCLE_ROLES, claims: {}, boardUrl: null } as unknown as HudState;
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} onQuery={() => {}} />));
};
const line = (id: string) => host.querySelector<HTMLElement>(`.card[data-id=${id}] .mach`);

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("a card's queued line", () => {
  it("draws queued in place of the machine state while the task's run waits in its queue", () => {
    mount([card("TASK-1", { runs: [run("succeeded"), run("queued")] }), card("TASK-2", { runs: [run("running"), run("failed")] })]);

    expect(line("TASK-1")!.classList.contains("queued")).toBe(true);
    expect(line("TASK-1")!.textContent).toContain("queued");
    expect(line("TASK-2")!.classList.contains("queued")).toBe(false);
    expect(line("TASK-2")!.textContent).toContain("lifecycle");
  });

  it("redraws when the queued run starts", () => {
    mount([card("TASK-1", { runs: [run("queued")] })]);
    expect(line("TASK-1")!.classList.contains("queued")).toBe(true);

    mount([card("TASK-1", { runs: [run("running")] })]);
    expect(line("TASK-1")!.classList.contains("queued")).toBe(false);
  });
});
