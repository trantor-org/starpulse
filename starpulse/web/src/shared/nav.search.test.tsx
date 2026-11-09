// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { BOARD_DRAWN } from "./boardDrawn";

// the canvas renderer needs a browser's 2D context; the navigator around it does not
vi.mock("../render/renderer", () => ({
  renderer: () => new Proxy({}, { get: () => () => {} }),
}));

let host: HTMLDivElement, root: Root;
const type = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const clear = () => host.querySelector<HTMLButtonElement>('#nav button[aria-label="Clear the search"]');

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  // the views load on demand: have this one loaded, so a mount that opens it draws it at once
  await import("../features/kanban/Kanban");
  root = createRoot(host);
  performance.mark(BOARD_DRAWN); // a page past its first frame: the navigator is filled
  await act(async () => root.render(<App />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  performance.clearMarks(BOARD_DRAWN);
  vi.unstubAllGlobals();
});

describe("the navigator's Star Map entry", () => {
  it("draws the orbit icon, a planet, a tilted orbit and a moon, in place of the bare ring", () => {
    const glyph = host.querySelector("#nav section.views .node i.g")!;

    expect(glyph.querySelectorAll("circle")).toHaveLength(2);
    expect(glyph.querySelector("ellipse")?.getAttribute("transform")).toBe("rotate(-28 12 12)");
    expect(glyph.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 24 24");
  });
});

describe("the Star Map navigator", () => {
  const remount = async (view: string) => {
    act(() => root.unmount());
    history.replaceState(null, "", `/?view=${view}`);
    root = createRoot(host);
    await act(async () => root.render(<App />));
  };

  it("opens on the search it last had, after a reload", async () => {
    type(host.querySelector<HTMLInputElement>("#q")!, "lint");
    await remount("constellation");

    expect(host.querySelector<HTMLInputElement>("#q")!.value).toBe("lint");
  });

  it("no longer draws the Layers section or its tree", () => {
    expect(host.querySelector("#nav section.layers")).toBeNull();
    expect(host.querySelector("#layers")).toBeNull();
    expect([...host.querySelectorAll("#nav h3")].map((h) => h.textContent)).not.toContain("Layers");
  });

  it("leaves the way back out to the canvas breadcrumb, after the navigator so it follows the fold", () => {
    const crumb = host.querySelector("#crumb")!;

    expect(crumb.textContent).toBe("Board");
    expect(host.querySelector("#nav")!.nextElementSibling?.tagName).toBe("NAV");
    expect(host.querySelector("#nav ~ #crumb")).toBe(crumb);
  });

  it("keeps the breadcrumb hidden on the Kanban", async () => {
    await remount("kanban");

    expect(host.querySelector("#crumb")?.classList).toContain("off");
  });
});

describe("the navigator search's clear button", () => {
  it("draws one ✕ only while the search holds text, and a click empties it and keeps the focus", () => {
    const input = host.querySelector<HTMLInputElement>("#q")!;

    expect(clear()).toBeNull();
    type(input, "needle");
    expect(host.querySelectorAll('#nav button[aria-label="Clear the search"]')).toHaveLength(1);

    const press = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    act(() => void clear()!.dispatchEvent(press));
    act(() => clear()!.click());

    expect(press.defaultPrevented).toBe(true);
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    expect(clear()).toBeNull();
  });
});

describe("the navigator's search slot", () => {
  const remount = async (view: string) => {
    act(() => root.unmount());
    history.replaceState(null, "", `/?view=${view}`);
    root = createRoot(host);
    await act(async () => root.render(<App />));
  };

  it("holds the Kanban search while the Kanban is open, under the Views and out of the toolbar", async () => {
    await remount("kanban");

    expect(host.querySelector("#nav #kbq")).not.toBeNull();
    expect(host.querySelector("#kb .filters #kbq")).toBeNull();
    expect(host.querySelector("#nav #q")).toBeNull();
  });

  it.each(["constellation", "kanban"])("is always open on the %s view: no fold button, no folded strip, and `[` changes nothing", async (view) => {
    await remount(view);

    act(() => void dispatchEvent(new KeyboardEvent("keydown", { key: "[" })));

    expect(host.querySelector("#fold")).toBeNull();
    expect(host.querySelector("#nv-mag")).toBeNull();
    expect(host.querySelector("#nav")!.classList.contains("folded")).toBe(false);
  });
});

describe("the navigator search's Matches while they scroll", () => {
  it("marks the list scrolling until the frame after it has rested 300 ms, so the rows it passes under a still pointer light nothing", () => {
    // the Matches draw only over a loaded tree; a box of that class in the navigator scrolls the same
    const matches = host.querySelector("#nav")!.appendChild(Object.assign(document.createElement("section"), { className: "away matches" }));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    try {
      const scrolling = () => matches.classList.contains("scrolling");
      act(() => void matches.dispatchEvent(new Event("scroll")));
      expect(scrolling()).toBe(true);
      act(() => void vi.advanceTimersByTime(200));
      act(() => void matches.dispatchEvent(new Event("scroll")));
      act(() => void vi.advanceTimersByTime(200));
      expect(scrolling()).toBe(true);
      act(() => void vi.advanceTimersByTime(120));
      expect(scrolling()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("ends the rest at a frame, after that frame's scroll events, so a long task that outlasts the rest cannot end it mid-scroll", () => {
    const matches = host.querySelector("#nav")!.appendChild(Object.assign(document.createElement("section"), { className: "away matches" }));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    try {
      const scrolling = () => matches.classList.contains("scrolling");
      act(() => void matches.dispatchEvent(new Event("scroll")));
      act(() => void vi.advanceTimersByTime(300));
      expect(scrolling()).toBe(true);
      act(() => void matches.dispatchEvent(new Event("scroll")));
      act(() => void vi.advanceTimersByTime(20));
      expect(scrolling()).toBe(true);
      act(() => void vi.advanceTimersByTime(320));
      expect(scrolling()).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
