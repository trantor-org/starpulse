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
const card = (id: string, lane: string, assignee: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: id, lane, milestone: "", labels: [], assignee, dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [], ...extra,
});

let host: HTMLDivElement, root: Root;
const mount = (cards: KanbanTask[]) => {
  const hud = { cards, names: {}, roles: LIFECYCLE_ROLES } as unknown as HudState;
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} onQuery={() => {}} />));
};
const turn = (agoS: number) => new Date((NOW - agoS) * 1000).toISOString();
const sess = (id: string) => host.querySelector<HTMLElement>(`.card[data-id=${id}] .who.sess`);

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("a working card's session activity", () => {
  it("draws how long an idle session has sat idle, a distinct unknown, and nothing while it works", () => {
    mount([
      card("TASK-1", "in_progress", "@agent-a", { sessionActivity: { state: "idle", last_turn_at: turn(9 * 3600) } }),
      card("TASK-2", "in_progress", "@agent-b", { sessionActivity: { state: "working", last_turn_at: turn(5) } }),
      card("TASK-3", "in_progress", "@agent-c", { sessionActivity: { state: "unknown" } }),
      card("TASK-4", "in_progress", "@agent-d"),
    ]);

    expect(sess("TASK-1")?.textContent).toBe("session idle 9h");
    expect(sess("TASK-2")).toBeNull();
    expect(sess("TASK-3")?.textContent).toBe("session unknown");
    expect(sess("TASK-4")).toBeNull();
  });
});
