// @vitest-environment jsdom
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kept, useViewActive } from "./Kept";

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

let mounts = 0, renders = 0;
/** A view with state of its own, so a remount shows as a reset count. */
function Counter({ label }: { label: string }) {
  const [n, setN] = useState(0);
  const active = useViewActive();
  renders++;
  useEffect(() => void mounts++, []);
  return <button data-label={label} data-active={String(active)} onClick={() => setN(n + 1)}>{n}</button>;
}
const show = (on: boolean, children: ReactNode) => act(async () => root.render(<Kept on={on}>{children}</Kept>));
const button = () => host.querySelector("button");
/** Lets the frames after a reveal pass, when the view goes live again. */
const frames = () => act(async () => { for (let i = 0; i < 3; i++) await new Promise((r) => requestAnimationFrame(r)); });

describe("Kept", () => {
  beforeEach(() => { mounts = 0; renders = 0; });

  it("mounts nothing until the view is first shown", async () => {
    await show(false, <Counter label="a" />);
    expect(button()).toBeNull();
  });

  it("keeps the view mounted with its state when it is left, and shows that state again on return", async () => {
    await show(true, <Counter label="a" />);
    await act(async () => button()!.click());
    await show(false, <Counter label="a" />);
    expect(button()?.textContent).toBe("1");
    await show(true, <Counter label="a" />);
    expect(button()?.textContent).toBe("1");
    expect(mounts).toBe(1);
  });

  it("makes a view that is left inert and tells it so, and a view that is shown neither", async () => {
    await show(true, <Counter label="a" />);
    expect(button()!.closest("[inert]")).toBeNull();
    expect(button()!.dataset.active).toBe("true");
    await show(false, <Counter label="a" />);
    expect(button()!.closest("[inert]")).not.toBeNull();
    expect(button()!.dataset.active).toBe("false");
  });

  it("does not render a view that is left when its parent renders again", async () => {
    await show(true, <Counter label="a" />);
    await show(false, <Counter label="a" />);
    const before = renders;
    await show(false, <Counter label="b" />);
    expect(renders).toBe(before);
    expect(button()!.dataset.label).toBe("a");
    await show(true, <Counter label="b" />);
    await frames();
    expect(button()!.dataset.label).toBe("b");
  });

  it("shows a view that is returned to at once, as it was left, and renders it and tells it it is active only frames later", async () => {
    await show(true, <Counter label="a" />);
    await show(false, <Counter label="a" />);
    const before = renders;
    await show(true, <Counter label="b" />);
    expect(button()!.closest("[inert]")).toBeNull();
    expect(button()!.dataset.label).toBe("a");
    expect(button()!.dataset.active).toBe("false");
    expect(renders).toBe(before);
    await frames();
    expect(button()!.dataset.label).toBe("b");
    expect(button()!.dataset.active).toBe("true");
  });

  it("pauses the animations running in a view that is left, and plays exactly those again once it is live", async () => {
    const anim = (playState: string) => ({ playState, pause: vi.fn(), play: vi.fn() });
    const running = anim("running"), still = anim("paused");
    const proto = Element.prototype as { getAnimations?: () => unknown[] };
    proto.getAnimations = () => [running, still];
    try {
      await show(true, <Counter label="a" />);
      await show(false, <Counter label="a" />);
      expect(running.pause).toHaveBeenCalledOnce();
      expect(still.pause).not.toHaveBeenCalled();
      await show(true, <Counter label="a" />);
      expect(running.play).not.toHaveBeenCalled();
      await frames();
      expect(running.play).toHaveBeenCalledOnce();
      expect(still.play).not.toHaveBeenCalled();
    } finally {
      delete proto.getAnimations;
    }
  });
});
