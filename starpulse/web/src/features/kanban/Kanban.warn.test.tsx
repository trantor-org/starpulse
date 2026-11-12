// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore, type Post } from "./move";
import { StartStore } from "./start";
import type { TaskRecord } from "./taskViewModel";

const WARNINGS = [{ reason: "Review needs a ready pull request: run `starpulse command run ready`", skill: "deliver" }, { reason: "Review needs every Acceptance Criterion checked", skill: "" }];
const task: KanbanTask = {
  id: "TASK-1", title: "title TASK-1", lane: "in_progress", milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false,
  moves: { review: { allowed: false, reason: WARNINGS[0].reason, skill: "deliver", actors: { operator: { allowed: true, reason: "", skill: "", warnings: WARNINGS } } } },
  entered: 0, created: null, workableSince: null, machines: [],
};
const record: TaskRecord = {
  title: "title TASK-1", profile: "", priority: "High", labels: [], milestone: "", dependencies: [], description: "", plan: "", notes: "",
  acceptanceCriteria: [], definitionOfDone: [], session: "",
};
const hud = { cards: [task], names: {}, roles: LIFECYCLE_ROLES, claims: {}, boardUrl: null } as unknown as HudState;

let host: HTMLDivElement, root: Root, post: ReturnType<typeof vi.fn<Post>>;
const settle = () => act(async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); });
const box = () => document.querySelector<HTMLElement>("#efa [role=alertdialog]");
const press = (label: string) => act(() => void [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === label)!.click());
const pickReview = () => {
  act(() => host.querySelector<HTMLElement>('#cols .card[data-id="TASK-1"]')!.click());
  act(() => void document.querySelector<HTMLElement>('.mvmenu [role="menuitem"].warn')!.click());
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ record }) })));
  post = vi.fn<Post>(async () => ({ ok: true }));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  const moves = new MoveStore(post);
  act(() => root.render(<Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the warn-and-confirm box from the task view's Move to", () => {
  it("lists each broken rule with Confirm and Cancel, and writes nothing until Confirm", async () => {
    pickReview();
    await settle();

    expect(box()?.textContent).toContain("Move TASK-1 to review?");
    expect(box()?.textContent).toContain("This move breaks 2 rules of the review lane.");
    expect(box()?.querySelectorAll(".rules .warn")).toHaveLength(2);
    expect(document.activeElement?.textContent).toBe("Cancel");
    expect(box()?.querySelector(".rules code")?.textContent).toBe("starpulse command run ready");
    expect(post).not.toHaveBeenCalled();
  });

  it("closes on Cancel with nothing written", async () => {
    pickReview();
    press("Cancel");
    await settle();

    expect(box()).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it("writes the move on Confirm and closes once the writer answers", async () => {
    pickReview();
    press("Confirm");
    await settle();

    expect(post).toHaveBeenCalledExactlyOnceWith("TASK-1", "review");
    expect(box()).toBeNull();
  });

  it("stays open on a refused Confirm with only Cancel live", async () => {
    post.mockResolvedValueOnce({ ok: false, reason: "changed", skill: "" });
    pickReview();
    press("Confirm");
    await settle();

    expect(box()?.querySelector('[role="alert"]')?.textContent).toContain("Not moved: changed");
    expect([...box()!.querySelectorAll("button")].map((b) => [b.textContent, b.disabled])).toEqual([["Cancel", false], ["Confirm", true]]);
  });

  it("cancels on Escape without closing the task view behind it", async () => {
    pickReview();
    act(() => void dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    await settle();

    expect(box()).toBeNull();
    expect(post).not.toHaveBeenCalled();
    expect(document.querySelector("[role=dialog]")).not.toBeNull();
  });
});

describe("a board whose streamed moves leave the guards unjudged", () => {
  it("offers the Move to warning and asks on the verdicts read when the task opened", async () => {
    const unjudged: KanbanTask = { ...task, moves: { review: { allowed: true, reason: "", skill: "" } } };
    const standing = vi.fn(async () => task.moves);
    const moves = new MoveStore(post, undefined, standing);
    act(() => root.render(<Kanban hud={{ ...hud, cards: [unjudged] } as HudState} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}} searchSlot={null} outlineSlot={null} />));
    act(() => host.querySelector<HTMLElement>('#cols .card[data-id="TASK-1"]')!.click());
    await settle();
    act(() => void document.querySelector<HTMLElement>('.mvmenu [role="menuitem"].warn')!.click());
    await settle();

    expect(standing).toHaveBeenCalledWith("TASK-1");
    expect(box()?.querySelectorAll(".rules .warn")).toHaveLength(2);
    expect(post).not.toHaveBeenCalled();
  });
});
