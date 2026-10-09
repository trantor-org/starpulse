// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BOARD_DRAWN } from "./shared/boardDrawn";

// the canvas renderer needs a browser's 2D context; this one records the calls the page makes on it
const calls: string[] = [];
vi.mock("./render/renderer", async (original) => ({
  ...(await original<typeof import("./render/renderer")>()),
  renderer: () => new Proxy({}, { get: (_t, name) => () => void calls.push(String(name)) }),
}));
vi.mock("./lazyViews", () => ({
  Kanban: () => <div id="kb" />,
  Dags: () => <div id="dg" />,
  AdminPage: () => <div id="admin" />,
  OrbitCard: () => <div id="og" />,
  prefetchViews: () => () => {},
}));

let host: HTMLDivElement, root: Root;
const node = (title: string) => [...host.querySelectorAll<HTMLElement>("#nav section.views:not(.admin-sec) .node")].find((n) => n.title === title)!;
const adminNode = () => host.querySelector<HTMLElement>("#nav section.admin-sec .node")!;
const resizes = () => calls.filter((c) => c === "resize").length;

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  calls.length = 0;
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  performance.mark(BOARD_DRAWN); // a page past its first frame: the navigator is filled
  await act(async () => root.render(<App />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.className = "";
  performance.clearMarks(BOARD_DRAWN);
  vi.unstubAllGlobals();
});

describe("the page sizing the canvas", () => {
  it("leaves the first sizing to the renderer's start, which has already laid out and drawn the board", () => {
    expect(calls).toContain("start");
    expect(resizes()).toBe(0);
  });

  it("shows the already-sized canvas again without rebuilding its scene", () => {
    act(() => node("Kanban").click());
    expect(resizes()).toBe(0);
    act(() => node("Star Map").click());
    expect(resizes()).toBe(0);
  });

  it("composites the Star Map surface before restoring its idle chrome", async () => {
    act(() => node("Kanban").click());
    expect(host.querySelector("#c")?.classList).toContain("off");
    expect(host.querySelector("#tip")?.classList).toContain("off");
    expect(host.querySelector("#panel")?.classList).toContain("off");
    expect(document.body.className).toBe("");

    act(() => node("Star Map").click());
    expect(host.querySelector("#c")?.classList).not.toContain("off");
    expect(host.querySelector("#tip")?.classList).toContain("off");
    expect(host.querySelector("#panel")?.classList).toContain("off");

    await act(async () => { for (let i = 0; i < 10; i++) await new Promise((resolve) => requestAnimationFrame(resolve)); });
    expect(host.querySelector("#tip")?.classList).not.toContain("off");
    expect(host.querySelector("#panel")?.classList).not.toContain("off");
  });

  it("hides Star Map-only chrome immediately and restores it after the reveal", async () => {
    const crumb = host.querySelector<HTMLElement>("#crumb")!;
    act(() => node("Kanban").click());
    expect(!crumb.isConnected || crumb.classList.contains("off")).toBe(true);

    act(() => node("Star Map").click());
    expect(host.querySelector("#crumb")?.classList).toContain("off");
    await act(async () => { for (let i = 0; i < 10; i++) await new Promise((resolve) => requestAnimationFrame(resolve)); });
    expect(host.querySelector("#crumb")?.classList).not.toContain("off");

    act(() => adminNode().click());
    expect(host.querySelector("#crumb")?.classList).toContain("off");
  });

  it("shows the time once, in the navigator's live line, with no second header clock", () => {
    expect(host.querySelector("#clock")).toBeNull();
  });
});
