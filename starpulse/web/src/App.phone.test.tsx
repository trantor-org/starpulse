// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { HudStore } from "./render/hud";
import { BOARD_DRAWN } from "./shared/boardDrawn";

// the page's boot holds a renderer that draws on a 2D context; this one records the calls the page makes on it
const boot = vi.hoisted(() => ({ held: null as object | null, calls: [] as string[] }));
vi.mock("./boot", () => ({ booted: () => boot.held }));
vi.mock("./lazyViews", () => ({
  Kanban: () => <div id="kb" />,
  Dags: () => <div id="dg" />,
  AdminPage: () => <div id="admin" />,
  OrbitCard: () => <div id="og" />,
  prefetchViews: () => () => {},
}));

let host: HTMLDivElement, root: Root;
const buttons = () => [...host.querySelectorAll<HTMLButtonElement>("#pnav button")];
const button = (label: string) => {
  const b = buttons().find((x) => x.textContent === label);
  expect(b, `the bar's ${label} button`).toBeDefined();
  return b!;
};
const tap = (label: string) => act(() => button(label).click());
const nav = () => host.querySelector<HTMLElement>("#nav")!;
const shown = () => nav().classList.contains("sheet");
const frames = () => act(async () => { for (let i = 0; i < 10; i++) await new Promise((resolve) => requestAnimationFrame(resolve)); });
const type = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });

/** Mounts the page past its first frame, over a Board with a Ready state, against a server that has a level above the Board or not. */
const mount = async (level: boolean) => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response("{}", { status: level || !String(url).includes("/api/level") ? 200 : 404 })));
  const store = new HudStore();
  store.set({ tree: { states: ["ready"], subs: {}, children: {} }, states: [{ id: "ready", name: "Ready", count: 2 }] });
  boot.held = {
    store,
    canvas: document.createElement("canvas"),
    tip: document.createElement("div"),
    panel: document.createElement("div"),
    renderer: new Proxy({}, { get: (_t, name) => () => void boot.calls.push(String(name)) }),
  };
  root = createRoot(host);
  performance.mark(BOARD_DRAWN); // a page past its first frame: the navigator is filled
  await act(async () => root.render(<App />));
  for (let i = 0; i < 5; i++) await act(async () => {}); // the level's answer
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  boot.calls.length = 0;
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  performance.clearMarks(BOARD_DRAWN);
  vi.unstubAllGlobals();
});

describe("the phone-width view bar", () => {
  it("draws a button per view and then More, in the navigator's order", async () => {
    await mount(false);

    expect(buttons().map((b) => b.textContent)).toEqual(["Star Map", "Kanban", "DAGs", "Admin", "More"]);
  });

  it("adds the Flow graph, before Admin, only when the server has a level above the Board", async () => {
    await mount(true);

    expect(buttons().map((b) => b.textContent)).toEqual(["Star Map", "Kanban", "DAGs", "Flow", "Admin", "More"]);
  });

  it("marks the view showing, and a tap on another button opens that view", async () => {
    await mount(false);
    expect(button("Star Map").getAttribute("aria-current")).toBe("page");
    expect(button("Kanban").getAttribute("aria-current")).toBeNull();

    tap("Kanban");
    await frames();

    expect(button("Kanban").getAttribute("aria-current")).toBe("page");
    expect(button("Star Map").getAttribute("aria-current")).toBeNull();
    expect(location.search).toBe("?view=kanban");
  });

  it("refits the Board on a tap on the Star Map while it shows, as the navigator's entry does", async () => {
    await mount(false);

    tap("Star Map");

    expect(boot.calls).toContain("fitView");
  });
});

describe("the phone-width navigator sheet", () => {
  it("keeps the navigator shut until More opens it over a scrim", async () => {
    await mount(false);
    expect(shown()).toBe(false);
    expect(host.querySelector("#pn-scrim")).toBeNull();
    expect(button("More").getAttribute("aria-expanded")).toBe("false");

    tap("More");

    expect(shown()).toBe(true);
    expect(host.querySelector("#pn-scrim")).not.toBeNull();
    expect(button("More").getAttribute("aria-expanded")).toBe("true");
  });

  it.each([
    ["Escape", () => act(() => void dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })))],
    ["its close button", () => act(() => host.querySelector<HTMLButtonElement>('#nav button[aria-label="Close the navigator"]')!.click())],
    ["a tap on the scrim", () => act(() => host.querySelector<HTMLElement>("#pn-scrim")!.click())],
    ["choosing a view in it", () => act(() => host.querySelector<HTMLElement>('#nav section.views .node[title="Kanban"]')!.click())],
    ["choosing a search hit", () => {
      type(host.querySelector<HTMLInputElement>("#q")!, "ready");
      act(() => host.querySelector<HTMLElement>("#nav .hit")!.click());
    }],
  ])("closes on %s", async (_name, close) => {
    await mount(false);
    tap("More");
    expect(shown()).toBe(true);

    close();

    expect(shown()).toBe(false);
    expect(host.querySelector("#pn-scrim")).toBeNull();
    expect(button("More").getAttribute("aria-expanded")).toBe("false");
  });
});

describe("the canvas ending above the bar", () => {
  const watch = () => {
    const watchers: (() => void)[] = [];
    vi.stubGlobal("ResizeObserver", class { constructor(cb: () => void) { watchers.push(cb); } observe() {} disconnect() {} });
    return () => act(() => watchers.forEach((w) => w()));
  };
  const height = (px: number) => Object.defineProperty(host.querySelector("#pnav"), "offsetHeight", { configurable: true, value: px });

  it("asks the renderer to fit again when the bar's height changes, and not while the bar is not drawn", async () => {
    const notify = watch();
    await mount(false);
    const resized = vi.fn();
    addEventListener("resize", resized);
    try {
      notify();
      expect(resized, "a page wider than the phone draws no bar").not.toHaveBeenCalled();

      height(54);
      notify();
      expect(resized, "the bar mounted at 54 px").toHaveBeenCalledTimes(1);
      notify();
      expect(resized, "the same height again").toHaveBeenCalledTimes(1);

      height(62);
      notify();
      expect(resized, "the text size grew the bar").toHaveBeenCalledTimes(2);
    } finally {
      removeEventListener("resize", resized);
    }
  });
});
