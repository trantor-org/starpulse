// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Preview } from "./Preview";

let host: HTMLDivElement, root: Root, ctx: Record<string, ReturnType<typeof vi.fn>>, raf: ReturnType<typeof vi.fn>;

/** A 2D context that records its calls: every method is a spy, and gradients accept color stops. */
const fakeContext = () => {
  const spies: Record<string, ReturnType<typeof vi.fn>> = {};
  return new Proxy(spies, {
    get: (_, k: string) => (spies[k] ??= vi.fn(() => ({ addColorStop() {} }))),
    set: () => true,
  });
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  ctx = fakeContext();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
  raf = vi.fn(() => 1);
  vi.stubGlobal("requestAnimationFrame", raf);
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the Admin Preview", () => {
  it("draws one still frame and starts no animation loop with Motion off", async () => {
    await act(async () => root.render(<Preview scale={100} compact={false} motion={false} />));

    expect(ctx.clearRect).toHaveBeenCalledTimes(1);
    expect(raf).not.toHaveBeenCalled();
  });

  it("loops the comet hop with Motion on", async () => {
    await act(async () => root.render(<Preview scale={100} compact={false} motion />));

    expect(raf).toHaveBeenCalled();
  });

  it("redraws its still frame when the theme changes", async () => {
    await act(async () => root.render(<Preview scale={100} compact={false} motion={false} />));

    act(() => void window.dispatchEvent(new Event("sp:theme")));

    expect(ctx.clearRect).toHaveBeenCalledTimes(2);
  });

  it("keeps the play edge on the kanban card and drops its labels when Compact", async () => {
    await act(async () => root.render(<Preview scale={100} compact motion={false} />));
    expect(host.querySelector(".pvcard.compact .foot2")).toBeNull();
    expect(host.querySelector(".pvcard .play.edge")).not.toBeNull();
  });
});
