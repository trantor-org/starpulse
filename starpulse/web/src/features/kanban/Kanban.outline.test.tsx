// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { Kanban } from "./Kanban";
import type { HudState } from "../../render/hud";
import type { KanbanTask } from "./kanban";
import { MoveStore } from "./move";
import { StartStore } from "./start";

const card = (id: string, lane: string, milestone: string): KanbanTask => ({
  id, title: id, lane, milestone, labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince: null, machines: [],
});
// m-1 is open (1 of 2 done), m-2 is finished, m-3 is open and the largest (0 of 3)
const cards = [
  card("TASK-1", "done", "m-1"), card("TASK-2", "ready", "m-1"),
  card("TASK-3", "done", "m-2"),
  card("TASK-4", "ready", "m-3"), card("TASK-5", "ready", "m-3"), card("TASK-6", "review", "m-3"),
];
const hud = { cards, names: {}, claims: {}, boardUrl: null } as unknown as HudState;

let host: HTMLDivElement, search: HTMLDivElement, outline: HTMLDivElement, root: Root;
const rows = () => [...outline.querySelectorAll<HTMLButtonElement>("button.ms")];
const shown = () => cards.map((c) => c.id).filter((id) => host.textContent?.includes(id));
const counter = () => host.querySelector(".shown")!.textContent;
const columnCounts = () => Object.fromEntries([...host.querySelectorAll<HTMLElement>("section[data-lane]")].map((s) => [s.dataset.lane, s.querySelector(".c")!.textContent]));
const clear = () => outline.querySelector<HTMLButtonElement>("button.clear");

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  history.replaceState(null, "", "/");
  search = document.body.appendChild(document.createElement("div"));
  outline = document.body.appendChild(document.createElement("div"));
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  const moves = new MoveStore(async () => ({ ok: true }) as never);
  act(() => root.render(
    <Kanban hud={hud} moves={moves} starts={new StartStore((async () => ({})) as never, moves)} compact={false} constellation={() => {}}
      searchSlot={search} outlineSlot={outline} onQuery={() => {}} />,
  ));
});
afterEach(() => {
  act(() => root.unmount());
  for (const el of [host, search, outline]) el.remove();
});

describe("the Kanban milestone outline in the navigator", () => {
  it("lists each open milestone with its ID and done/total, largest first, under a Milestones heading with no clear ✕", () => {
    expect(outline.querySelector("h3")!.textContent).toBe("Milestones");
    expect(rows().map((r) => [r.querySelector(".id")!.textContent, r.querySelector(".w")!.textContent])).toEqual([["m-3", "0/3"], ["m-1", "1/2"]]);
    expect(rows().map((r) => r.querySelector<HTMLElement>(".bar i")!.style.width)).toEqual(["0%", "50%"]);
    expect(clear()).toBeNull();
    expect(host.querySelector(".filters")!.textContent).not.toContain("m-1");
  });

  it("sets the Kanban milestone filter on a click: only that milestone's cards show and the counts follow", () => {
    expect(shown()).toEqual(["TASK-1", "TASK-2", "TASK-3", "TASK-4", "TASK-5", "TASK-6"]);

    act(() => rows()[1].click());

    expect(shown()).toEqual(["TASK-1", "TASK-2"]);
    expect(rows().map((r) => r.classList.contains("on"))).toEqual([false, true]);
    expect(counter()).toBe("2 of 6 tasks");
    expect(columnCounts()).toMatchObject({ ready: "1", done: "1", review: "0" });
    expect(host.querySelector(".filters")!.textContent).toContain("m-1");
    expect(clear()!.textContent).toBe("clear ✕");
  });

  it("clears on a second click of the chosen row", () => {
    act(() => rows()[0].click());
    expect(shown()).toEqual(["TASK-4", "TASK-5", "TASK-6"]);

    act(() => rows()[0].click());

    expect(shown()).toHaveLength(6);
    expect(rows().some((r) => r.classList.contains("on"))).toBe(false);
    expect(clear()).toBeNull();
  });

  it("clears on clear ✕ and moves the choice when another row is clicked", () => {
    act(() => rows()[1].click());
    act(() => rows()[0].click());
    expect(shown()).toEqual(["TASK-4", "TASK-5", "TASK-6"]);

    act(() => clear()!.click());

    expect(shown()).toHaveLength(6);
    expect(counter()).toBe("6 of 6 tasks");
    expect(clear()).toBeNull();
  });

  it("follows the toolbar's Milestone chip, which holds the same filter", () => {
    act(() => rows()[0].click());
    act(() => host.querySelector<HTMLButtonElement>(".filters button.clear")!.click());

    expect(rows().some((r) => r.classList.contains("on"))).toBe(false);
    expect(shown()).toHaveLength(6);
  });
});
