// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Roles } from "../../api/types.gen";
import { applyPack, packTokens } from "../../tests/themeFixtures";
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
  applyPack("starpulse");
});
const mount = (onClose = () => undefined) =>
  act(() => root.render(<SunsDrillIn tasks={[task("TASK-1", "In Progress"), task("TASK-2", "In Progress"), task("TASK-3", "Ready")]} roles={roles} task="TASK-1" onClose={onClose} />));
const button = (label: string) => host.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!;
const fleet = () => [...host.querySelectorAll('nav[aria-label="In Progress tasks"] button')].map((b) => b.getAttribute("aria-label"));

describe("SunsDrillIn", () => {
  it("repaints the scene in a new theme's colours when the theme changes, with no remount", () => {
    mount();
    const dots = () => [...host.querySelectorAll<HTMLElement>("span")].map((e) => e.getAttribute("style") ?? "").join(" ");
    expect(dots()).toContain(packTokens("starpulse").waits);

    act(() => void applyPack("nord"));

    expect(dots()).toContain(packTokens("nord").waits);
    expect(dots()).not.toContain(packTokens("starpulse").waits);
  });

  it("reads each task's moves again every 5 seconds while it is open, so a phase a task enters is drawn without a reload", async () => {
    vi.useFakeTimers();
    try {
      mount();
      const reads = () => vi.mocked(fetch).mock.calls.filter(([u]) => String(u).includes("task=TASK-2")).length;
      await act(async () => void (await vi.advanceTimersByTimeAsync(0)));
      const first = reads();
      expect(first).toBeGreaterThan(0);

      await act(async () => void (await vi.advanceTimersByTimeAsync(5_000)));

      expect(reads()).toBeGreaterThan(first);
    } finally {
      vi.useRealTimers();
    }
  });

  it("lists the In Progress tasks in its Tasks strip and shows the drilled one", () => {
    mount();
    expect(fleet().map((a) => a?.split(" ")[0])).toEqual(["TASK-1", "TASK-2"]);
    expect(host.textContent).toContain("Board › In Progress");
    expect(host.textContent).toContain("2 tasks · showing TASK-1");
  });

  it("lists the In Progress tasks in the Navigator's slot when the shell gives it one, each with its phase and progress bar, and none in its header", () => {
    const slot = document.body.appendChild(document.createElement("section"));
    act(() => root.render(<SunsDrillIn tasks={[task("TASK-1", "In Progress"), task("TASK-2", "In Progress")]} roles={roles} task="TASK-2" onClose={() => undefined} navSlot={slot} />));

    const rows = [...slot.querySelectorAll<HTMLButtonElement>('nav[aria-label="In Progress tasks"] button')];
    expect(rows.map((b) => b.getAttribute("aria-label")?.split(" ")[0])).toEqual(["TASK-1", "TASK-2"]);
    expect(slot.textContent).toMatch(/Tasks.*In Progress\s*2/);
    expect(rows[1].getAttribute("aria-current")).toBe("true");
    expect(rows.every((b) => b.querySelector("i[style*='linear-gradient']"))).toBe(true);
    expect(host.querySelector("#sd header nav")).toBeNull();

    act(() => rows[0].click());
    expect(host.textContent).toContain("showing TASK-1");
    slot.remove();
  });

  it("draws inside the app shell: no copy of the Navigator, search or Recent, no fixed overlay and no scaled stage", () => {
    mount();
    const region = host.querySelector<HTMLElement>("#sd")!;

    expect(region).not.toBeNull();
    expect(region.style.position).not.toBe("fixed");
    expect(host.innerHTML).not.toMatch(/scale\(/);
    for (const copy of ["STARPULSE", "search…", "VIEWS", "RECENT"]) expect(host.textContent).not.toContain(copy);
    expect(host.querySelector('nav[aria-label="Tasks"], section[aria-label="Recent"]')).toBeNull();
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

  it("picks another task from the Tasks strip", () => {
    mount();
    act(() => host.querySelector<HTMLButtonElement>('nav[aria-label="In Progress tasks"] button[aria-label^="TASK-2"]')!.click());
    expect(host.textContent).toContain("showing TASK-2");
  });

  it("plays the replay and pauses it", () => {
    mount();
    act(() => button("Play replay").click());
    expect(button("Pause replay")).not.toBeNull();
  });

  it("paints its surfaces and text from the theme's tokens, so a theme change repaints it with no reload", () => {
    mount();
    const stage = host.querySelector<HTMLElement>(".sd-stage")!.firstElementChild as HTMLElement;

    // the sky is the section's own, from the stylesheet's theme tokens, so the stage paints none over it
    expect(stage.style.background).toBe("");
    expect(stage.style.color).toBe("var(--ink)");
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

  it("steps out one level per right-click, Escape or Backspace, as the Star Map does, and closes to the Board from the top", () => {
    const close = vi.fn();
    mount(close);
    const sd = host.querySelector<HTMLElement>("#sd")!;
    const rightClick = () => {
      const e = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
      act(() => void sd.dispatchEvent(e));
      return e;
    };

    act(() => button("Play replay").click());
    expect(rightClick().defaultPrevented).toBe(true);
    expect(button("Play replay")).not.toBeNull();
    expect(host.querySelector('[aria-label="Back to live"]')).toBeNull();
    expect(close).not.toHaveBeenCalled();

    rightClick();
    expect(close).toHaveBeenCalledTimes(1);

    // the Star Map under the drill-in keeps its own Escape and Backspace, so the key it takes reaches no one else
    const starMap = vi.fn();
    addEventListener("keydown", starMap);
    const press = (key: string) => act(() => void document.body.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true })));
    act(() => button("Play replay").click());
    press("Backspace");
    expect(host.querySelector('[aria-label="Back to live"]')).toBeNull();
    expect(close).toHaveBeenCalledTimes(1);
    press("Escape");
    expect(close).toHaveBeenCalledTimes(2);
    removeEventListener("keydown", starMap);
    expect(starMap).not.toHaveBeenCalled();
  });

  it("leaves Backspace to a text field that has focus", () => {
    const close = vi.fn();
    mount(close);
    const field = document.body.appendChild(document.createElement("input"));
    act(() => void field.dispatchEvent(new KeyboardEvent("keydown", { key: "Backspace", bubbles: true })));
    field.remove();
    expect(close).not.toHaveBeenCalled();
  });
});
