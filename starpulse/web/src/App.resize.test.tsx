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

let host: HTMLDivElement, root: Root;
const node = (title: string) => [...host.querySelectorAll<HTMLElement>("#nav section.views:not(.admin-sec) .node")].find((n) => n.title === title)!;
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

  it("refits the canvas once the Star Map is the page again", () => {
    act(() => node("Kanban").click());
    expect(resizes()).toBe(0);
    act(() => node("Star Map").click());
    expect(resizes()).toBe(1);
  });
});
