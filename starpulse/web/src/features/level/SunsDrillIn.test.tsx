// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Roles } from "../../api/types.gen";
import { SunsDrillIn, type DrillTask } from "./SunsDrillIn";
import { drillBoard } from "./sunsDrill";

const roles = { working: "In Progress" } as Roles;
const task = (id: string, lane: string) => ({ id, title: `Title ${id}`, lane, assignee: "@agent-standard-high" }) as DrillTask;
let host: HTMLDivElement, root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("requestAnimationFrame", () => 0);
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
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
  act(() => root.render(<SunsDrillIn tasks={[task("TASK-1", "In Progress"), task("TASK-2", "Ready")]} roles={roles} task="TASK-1" onClose={onClose} />));

describe("SunsDrillIn", () => {
  it("titles its left panel Tasks and lists only the In Progress tasks", () => {
    mount();
    expect(host.querySelector("nav h3")?.textContent).toBe("Tasks");
    const rows = [...host.querySelectorAll("nav button")].map((b) => b.textContent);
    expect(rows.some((r) => r?.includes("TASK-1"))).toBe(true);
    expect(rows.some((r) => r?.includes("TASK-2"))).toBe(false);
  });

  it("starts live, with play unavailable until the scrubber leaves live, and Live pressed", () => {
    mount();
    const by = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
    expect((by("Play") as HTMLButtonElement).disabled).toBe(true);
    expect(by("Live").getAttribute("aria-pressed")).toBe("true");
  });

  it("scrubbing back leaves live and offers Play; Live returns", () => {
    mount();
    const range = host.querySelector<HTMLInputElement>('input[type="range"]')!;
    const by = (name: string) => [...host.querySelectorAll("button")].find((b) => b.textContent === name)! as HTMLButtonElement;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    act(() => { set.call(range, "1000"); range.dispatchEvent(new Event("input", { bubbles: true })); });
    expect(by("Live").getAttribute("aria-pressed")).toBe("false");
    expect(by("Play").disabled).toBe(false);
    act(() => by("Live").click());
    expect(by("Live").getAttribute("aria-pressed")).toBe("true");
  });

  it("shows a sun's details on hover and pins its data on click, with no legend", () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
    mount();
    act(() => frames.splice(0).forEach((f) => f(0)));
    const board = drillBoard({ id: "TASK-1" }, [], 0, 0).board, sun = board.suns.find((s) => s.id === "build")!;
    const canvas = host.querySelector("canvas")!;
    canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: board.width, height: board.height }) as DOMRect;
    const mouse = (type: string) => new MouseEvent(type, { bubbles: true, clientX: sun.x, clientY: sun.y });
    act(() => void canvas.dispatchEvent(mouse("mousemove")));
    expect(host.querySelector('[role="tooltip"]')?.textContent).toContain("Build");
    expect(host.querySelector('[aria-label="Data"]')).toBeNull();
    act(() => void canvas.dispatchEvent(mouse("click")));
    expect(host.querySelector('[aria-label="Data"]')?.textContent).toContain("round 1 of 1");
    expect(host.textContent).not.toMatch(/legend/i);
  });

  it("keeps its canvas in the flow, not pinned over the panel by the page's fixed canvas rule", () => {
    mount();
    expect(host.querySelector("canvas")!.style.position).toBe("static");
  });

  it("closes", () => {
    const close = vi.fn();
    mount(close);
    act(() => [...host.querySelectorAll("button")].find((b) => b.textContent === "Close")!.click());
    expect(close).toHaveBeenCalled();
  });
});
