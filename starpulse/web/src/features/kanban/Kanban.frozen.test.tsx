// @vitest-environment jsdom
// A frozen task shows on its kanban card, and its card does not drag.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import { Kanban } from "./Kanban";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const frozen = { at: "2026-11-25T20:00:00Z", by: "operator", reason: "PR 10702 merged mid-rework" };
const card = (id: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: `title ${id}`, lane: "ready", milestone: "m-1", labels: [], assignee: "", dependencies: [], openDeps: 0,
  prs: [], description: "", live: null, released: false, moves: { review: { allowed: true } }, entered: 100, created: null,
  workableSince: null, machines: [], ...extra,
});

let host: HTMLDivElement, root: Root, post: ReturnType<typeof vi.fn>;
const show = (cards: KanbanTask[]) => {
  const hud = { cards, names: { ready: "Ready", review: "Review" }, roles: LIFECYCLE_ROLES, claims: {}, settled: [], boardUrl: null } as unknown as HudState;
  const moves = new MoveStore(post as never);
  act(() => root.render(
    <Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false}
      constellation={() => {}} searchSlot={null} outlineSlot={null} />,
  ));
};
const at = (id: string) => host.querySelector<HTMLElement>(`.card[data-id="${id}"]`)!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.scrollIntoView = () => {};
  post = vi.fn(async () => ({ ok: true }));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("a frozen Kanban card", () => {
  it("carries the frozen class and a snowflake naming who froze it and why", () => {
    show([card("T-1", { frozen }), card("T-2")]);

    expect(at("T-1").classList.contains("frozen")).toBe(true);
    const glyph = at("T-1").querySelector<HTMLElement>(".ice");
    expect(glyph?.textContent).toBe("❄");
    expect(glyph?.title).toBe("Frozen by operator: PR 10702 merged mid-rework");
    expect(at("T-2").classList.contains("frozen")).toBe(false);
    expect(at("T-2").querySelector(".ice")).toBeNull();
  });

  it("does not drag, where the same card unfrozen does", async () => {
    const drag = async (id: string) => {
      const fire = (target: EventTarget, type: string, x: number) =>
        act(() => void target.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: 10 })));
      const review = host.querySelector<HTMLElement>('#cols .col[data-lane="review"]')!;
      document.elementFromPoint = () => review;
      fire(at(id), "pointerdown", 10);
      fire(window, "pointermove", 60);
      fire(window, "pointermove", 120);
      fire(window, "pointerup", 120);
      await act(async () => {});
    };

    show([card("T-1", { frozen })]);
    await drag("T-1");
    expect(post).not.toHaveBeenCalled();

    show([card("T-1")]);
    await drag("T-1");
    expect(post).toHaveBeenCalledWith("T-1", "review", "ready");
  });
});
