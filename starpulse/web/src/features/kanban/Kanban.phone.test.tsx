// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HudState } from "../../render/hud";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import { Kanban } from "./Kanban";
import type { KanbanTask } from "./kanbanModel";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const card = (id: string, lane: string, moves: KanbanTask["moves"] = {}): KanbanTask => ({
  id, title: `title ${id}`, lane, milestone: "m-1", labels: [], assignee: "", dependencies: [], openDeps: 0,
  prs: [], description: "", live: null, released: false, moves, entered: 100, created: null, workableSince: null, machines: [],
});
const LANES = { ready: "Ready", waiting: "Waiting", in_progress: "In Progress", review: "Review", needs_attention: "Needs attention", done: "Done" };
const board = (cards: KanbanTask[], names: Record<string, string> = LANES) => ({ cards, names, roles: names === LANES ? LIFECYCLE_ROLES : {}, claims: {}, settled: [], boardUrl: null }) as unknown as HudState;

let host: HTMLDivElement, root: Root, post: ReturnType<typeof vi.fn>;
const show = (hud: HudState) => {
  const moves = new MoveStore(post as never);
  act(() => root.render(
    <Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false}
      constellation={() => {}} searchSlot={null} outlineSlot={null} />,
  ));
};
const tabs = () => [...host.querySelectorAll<HTMLElement>("#kb .lanes [role=tab]")];
const shown = () => [...host.querySelectorAll<HTMLElement>("#cols .col.on")].map((c) => c.dataset.lane);

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

describe("the Kanban lane strip", () => {
  const cards = [card("T-1", "ready"), card("T-2", "ready"), card("T-3", "in_progress"), card("T-4", "review")];

  it("has one tab per column, each with its lane's count", () => {
    show(board(cards));

    expect(tabs().map((t) => [t.dataset.lane, t.querySelector(".c")?.textContent])).toEqual([
      ["ready", "2"], ["waiting", "0"], ["in_progress", "1"], ["review", "1"], ["needs_attention", "0"], ["done", "0"],
    ]);
  });

  it("opens on In Progress, with that lane the only one carrying the shown class", () => {
    show(board(cards));

    expect(shown()).toEqual(["in_progress"]);
    expect(tabs().filter((t) => t.getAttribute("aria-selected") === "true").map((t) => t.dataset.lane)).toEqual(["in_progress"]);
  });

  it("opens on the first column when the board has no In Progress lane", () => {
    show(board([card("T-1", "todo")], { todo: "To do", doing: "Doing" }));

    expect(tabs().map((t) => t.dataset.lane)).toEqual(["todo", "doing"]);
    expect(shown()).toEqual(["todo"]);
  });

  it("shows the lane whose tab is tapped", () => {
    show(board(cards));

    act(() => tabs().find((t) => t.dataset.lane === "done")!.click());

    expect(shown()).toEqual(["done"]);
    expect(tabs().filter((t) => t.getAttribute("aria-selected") === "true").map((t) => t.dataset.lane)).toEqual(["done"]);
  });
});

describe("a pointer drag on a Kanban card", () => {
  const movable = card("T-1", "ready", { review: { allowed: true } });
  const fire = (target: EventTarget, type: string, x: number, y: number) =>
    act(() => void target.dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0, clientX: x, clientY: y })));
  const drag = async () => {
    show(board([movable]));
    const review = host.querySelector<HTMLElement>('#cols .col[data-lane="review"]')!;
    document.elementFromPoint = () => review;
    fire(host.querySelector('[data-id="T-1"]')!, "pointerdown", 10, 10);
    fire(window, "pointermove", 60, 10);
    fire(window, "pointermove", 120, 10);
    fire(window, "pointerup", 120, 10);
    await act(async () => {});
  };
  const phone = (narrow: boolean) => vi.stubGlobal("matchMedia", (query: string) => ({ matches: narrow && query === "(max-width: 900px)", addEventListener() {}, removeEventListener() {} }));

  it("starts no move and sends no write at 900px and narrower, so the lane scrolls under a finger", async () => {
    phone(true);
    await drag();

    expect(post).not.toHaveBeenCalled();
    expect(host.querySelector(".lift")).toBeNull();
    expect(document.body.classList.contains("dragging")).toBe(false);
  });

  it("still moves the card above 900px", async () => {
    phone(false);
    await drag();

    expect(post).toHaveBeenCalledWith("T-1", "review");
  });
});
