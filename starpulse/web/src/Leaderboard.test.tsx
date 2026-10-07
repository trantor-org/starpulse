// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanban";
import { Leaderboard } from "./Leaderboard";

const NOW = 1_000_000;
const card = (id: string, lane: string, workableSince: number | null): KanbanTask => ({
  id, title: `title of ${id}`, lane, milestone: "", labels: [], assignee: "", dependencies: [], openDeps: 0, prs: [], description: "", live: null, released: false, moves: {}, entered: 0, created: null, workableSince, machines: [],
});
const cards = [
  card("TASK-1", "in_progress", NOW - 2 * 86400), card("TASK-2", "waiting", NOW - 3 * 3600), card("TASK-3", "waiting", null), card("TASK-4", "ready", NOW - 600),
];

let host: HTMLDivElement, root: Root;
const open = vi.fn();
const draw = (tasks = cards) => act(() => root.render(<Leaderboard tasks={tasks} now={NOW} open={open} />));
const rows = () => [...host.querySelectorAll<HTMLButtonElement>("button.lb-row")];

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  open.mockReset();
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the Star Map navigator's Leaderboard", () => {
  it("draws a Leaderboard heading with 'by status', a count row per status and a row per task with its ID and age", () => {
    draw();
    expect(host.querySelector("h3")!.textContent).toBe("Leaderboardby status");
    expect([...host.querySelectorAll(".lb-grp")].map((g) => g.textContent)).toEqual(["Working1", "Waiting1", "Ready1"]);
    expect(rows().map((r) => [r.querySelector(".id")!.textContent, r.querySelector(".w")!.textContent])).toEqual([["TASK-1", "2d"], ["TASK-2", "3h"], ["TASK-4", "10m"]]);
    expect(rows().map((r) => r.querySelector<HTMLElement>(".bar i")!.style.width)).toEqual(["100%", "6%", "2%"]);
  });

  it("titles a status's count row with how many more can't be worked yet, only when some are held", () => {
    draw();
    expect([...host.querySelectorAll<HTMLElement>(".lb-grp")].map((g) => g.title)).toEqual(["", "1 more can't be worked yet", ""]);
  });

  it("draws nothing when no task is workable", () => {
    draw([card("TASK-1", "ready", null)]);
    expect(host.innerHTML).toBe("");
  });

  it("opens the task on a click and on Enter, once each", () => {
    draw();
    act(() => rows()[1].click());
    expect(open.mock.calls).toEqual([["TASK-2"]]);

    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    act(() => { rows()[2].dispatchEvent(enter); });
    expect(open.mock.calls).toEqual([["TASK-2"], ["TASK-4"]]);
    expect(enter.defaultPrevented).toBe(true);
  });
});
