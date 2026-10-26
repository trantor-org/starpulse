// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Roles } from "../../api/types.gen";
import { SunsDrillIn, type DrillTask } from "./SunsDrillIn";

const roles = { working: "In Progress" } as Roles;
const task = (id: string, lane: string) => ({ id, title: `Title ${id}`, lane, assignee: "@agent-standard-high" }) as DrillTask;
let host: HTMLDivElement, root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ events: [] }), { status: 200 })));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});
const mount = (onClose = () => undefined) =>
  act(() => root.render(<SunsDrillIn tasks={[task("TASK-1", "In Progress"), task("TASK-2", "In Progress"), task("TASK-3", "Ready")]} roles={roles} task="TASK-1" onClose={onClose} />));
const button = (label: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;
const fleet = () => [...host.querySelectorAll('nav[aria-label="Tasks"] button')].map((b) => b.getAttribute("aria-label"));

describe("SunsDrillIn", () => {
  it("lists the In Progress tasks in its Tasks panel and shows the drilled one", () => {
    mount();
    expect(fleet().map((a) => a?.split(" ")[0])).toEqual(["TASK-1", "TASK-2"]);
    expect(host.textContent).toContain("Board › In Progress");
    expect(host.textContent).toContain("2 tasks · showing TASK-1");
  });

  it("counts the board's tasks and DAGs in its Views panel", () => {
    act(() => root.render(<SunsDrillIn tasks={[task("TASK-1", "In Progress")]} roles={roles} task="TASK-1" dags={103} onClose={() => undefined} />));
    expect(host.textContent).toMatch(/Kanban1DAGs103/);
  });

  it("draws the drilled task before the board's tasks have arrived", () => {
    act(() => root.render(<SunsDrillIn tasks={[]} roles={roles} task="TASK-1" onClose={() => undefined} />));
    expect(fleet().map((a) => a?.split(" ")[0])).toEqual(["TASK-1"]);
    expect(host.textContent).toContain("1 tasks · showing TASK-1");
  });

  it("draws the approved board: its phases and the Board's entries and exits", () => {
    mount();
    for (const t of ["Build", "Deliver", "Review fix"]) expect(host.textContent).toContain(t);
    expect(button("From Ready")).not.toBeNull();
  });

  it("shows a tooltip on hover and pins its details on click, closed by ×", () => {
    mount();
    act(() => void button("From Ready").dispatchEvent(new MouseEvent("mouseover", { bubbles: true })));
    expect(host.querySelector('[role="tooltip"]')?.textContent).toContain("From Ready");
    act(() => button("From Ready").click());
    expect(host.querySelector('[aria-label="Details"]')?.textContent).toContain("lands on");
    act(() => button("Close details").click());
    expect(host.querySelector('[aria-label="Details"]')).toBeNull();
  });

  it("picks another task from the Tasks panel", () => {
    mount();
    act(() => host.querySelector<HTMLButtonElement>('nav[aria-label="Tasks"] button[aria-label^="TASK-2"]')!.click());
    expect(host.textContent).toContain("showing TASK-2");
  });

  it("plays the replay and pauses it", () => {
    mount();
    act(() => button("Play replay").click());
    expect(button("Pause replay")).not.toBeNull();
  });

  it("draws nothing yellow", () => {
    mount();
    expect(host.innerHTML).not.toMatch(/#fbbf24|#fcd34d|#fde68a|251,\s*191,\s*36/i);
  });

  it("closes from the Board crumb and on Escape", () => {
    const close = vi.fn();
    mount(close);
    act(() => button("Back to the Board").click());
    act(() => void window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(close).toHaveBeenCalledTimes(2);
  });
});
