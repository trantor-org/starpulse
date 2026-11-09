// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOARD_DRAWN, useBoardDrawn } from "./boardDrawn";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function Probe({ ready }: { ready: boolean }) {
  useBoardDrawn(ready);
  return null;
}

let root: Root, frames: FrameRequestCallback[];
beforeEach(() => {
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => frames.push(cb));
  performance.clearMarks(BOARD_DRAWN);
  root = createRoot(document.createElement("div"));
});
afterEach(() => {
  act(() => root.unmount());
  vi.unstubAllGlobals();
});
const marks = () => performance.getEntriesByName(BOARD_DRAWN).length;

describe("the board-drawn mark", () => {
  it("is not set while the page holds no board", () => {
    act(() => root.render(<Probe ready={false} />));
    for (const f of frames) f(0);

    expect(marks()).toBe(0);
  });

  it("is set in the frame after the board first reaches the page, not at the commit that shows it", () => {
    act(() => root.render(<Probe ready={false} />));
    act(() => root.render(<Probe ready />));
    expect(marks()).toBe(0);

    for (const f of frames) f(0);

    expect(marks()).toBe(1);
  });

  it("is set once: later boards leave the first frame's time", () => {
    act(() => root.render(<Probe ready />));
    act(() => root.render(<Probe ready={false} />));
    act(() => root.render(<Probe ready />));
    for (const f of frames) f(0);

    expect(marks()).toBe(1);
  });
});
