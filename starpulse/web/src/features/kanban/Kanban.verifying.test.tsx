// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";

const ROLES = { ...LIFECYCLE_ROLES, verifying: "verifying" };
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const NOW = Date.now() / 1000;
const merged = { number: 7, url: "https://github.com/o/r/pull/7", merged: true, closed: false, checks: "pass", threads: 0 } as never;
const card = (id: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: id, lane: "verifying", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
  live: { machine: "verify", state: "applied", at: NOW - 600 }, ...extra,
});

let host: HTMLDivElement, root: Root;
const mount = (cards: KanbanTask[]) => {
  const hud = { cards, names: { verifying: "Verifying" }, roles: ROLES, claims: {}, boardUrl: null } as unknown as HudState;
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} onQuery={() => {}} />));
};

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

describe("a verifying card", () => {
  it("sits in the Verifying column with its merged pull request and the post-merge QA stage it waits at", () => {
    mount([card("TASK-1", { prs: [merged] }), card("TASK-2", { lane: "review", prs: [merged], live: null })]);

    expect(host.querySelector(".col[data-lane=verifying] .card[data-id=TASK-1]")).not.toBeNull();
    expect(host.querySelector(".col[data-lane=review] .card[data-id=TASK-1]")).toBeNull();
    expect(host.querySelector(".card[data-id=TASK-1] .pr.merged")!.textContent).toContain("#7");
    const waits = host.querySelector<HTMLElement>(".card[data-id=TASK-1] .mach.verifying")!;
    expect(waits.textContent).toContain("applied");
    expect(host.querySelector(".card[data-id=TASK-2] .mach.verifying")).toBeNull();
  });
});
