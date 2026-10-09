// @vitest-environment jsdom
import { act, lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isKeptRevealed, Kept, revealKept, useViewActive } from "./Kept";

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  // frames and timers pass only when a test steps them, so a loaded runner cannot slip one in between its checks
  vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "setTimeout", "clearTimeout"] });
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
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
const show = (on: boolean, children: ReactNode, warm = false) => act(async () => root.render(<Kept on={on} warm={warm}>{children}</Kept>));
const button = () => host.querySelector("button");
/** Lets the frames after a reveal pass, when the view goes live again. */
const frames = async () => { for (let i = 0; i < 3; i++) await frame(); };
/** Passes one frame. */
const frame = () => act(async () => void vi.advanceTimersToNextFrame());
/** Lets the timer pass that mounts a warmed view after the frame that asked for it. */
const tick = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
/** Lets the housekeeping after the measured reveal window pass. */
const settled = frames;

describe("Kept", () => {
  beforeEach(() => { mounts = 0; renders = 0; });

  it("mounts nothing until the view is first shown", async () => {
    await show(false, <Counter label="a" />);
    expect(button()).toBeNull();
  });

  it("reveals an already-mounted named view without waiting for React to render the page", async () => {
    await act(async () => root.render(<><Kept name="a" on><span>a</span></Kept><Kept name="b" on={false} warm><span>b</span></Kept></>));
    await frames();

    expect(revealKept("b")).toBe(true);
    const hidden = wrapper("a").firstElementChild as HTMLElement;
    const visible = wrapper("b").firstElementChild as HTMLElement;
    expect(hidden.style.opacity).toBe("0");
    expect(hidden.hasAttribute("inert")).toBe(false);
    expect(visible.style.opacity).toBe("1");
    expect(visible.hasAttribute("inert")).toBe(false);
    expect(isKeptRevealed("a")).toBe(false);
    expect(isKeptRevealed("b")).toBe(true);
    expect(wrapper("a").hasAttribute("inert")).toBe(false);
    expect(wrapper("b").hasAttribute("inert")).toBe(true);
    expect(revealKept("missing")).toBe(false);
    await frames();
    expect(hidden.hasAttribute("inert")).toBe(false);
    expect(visible.hasAttribute("inert")).toBe(false);
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
    await settled();
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
    await settled();
    expect(button()!.dataset.label).toBe("b");
  });

  it("shows a view that is returned to at once, as it was left, and updates it after the reveal window", async () => {
    await show(true, <Counter label="a" />);
    await show(false, <Counter label="a" />);
    await settled();
    const before = renders;
    await show(true, <Counter label="b" />);
    expect(button()!.closest("[inert]")).toBeNull();
    expect(button()!.dataset.label).toBe("a");
    expect(button()!.dataset.active).toBe("false");
    expect(renders).toBe(before);
    await settled();
    expect(button()!.closest("[inert]")).toBeNull();
    expect(button()!.dataset.label).toBe("b");
    expect(button()!.dataset.active).toBe("true");
  });

  it("does not enumerate document animations while leaving or returning to a view", async () => {
    await show(true, <Counter label="a" />);
    const anim = (playState: string, target: Element) => ({ playState, effect: { target }, pause: vi.fn(), play: vi.fn() });
    const running = anim("running", button()!);
    const doc = document as { getAnimations?: () => unknown[] };
    const getAnimations = vi.fn(() => [running]);
    doc.getAnimations = getAnimations;
    try {
      await show(false, <Counter label="a" />);
      expect(getAnimations).not.toHaveBeenCalled();
      await frames();
      expect(getAnimations).not.toHaveBeenCalled();
      expect(running.pause).not.toHaveBeenCalled();
      await show(true, <Counter label="a" />);
      await frames();
      expect(getAnimations).not.toHaveBeenCalled();
      expect(running.play).not.toHaveBeenCalled();
    } finally {
      delete doc.getAnimations;
    }
  });

  it("mounts a warmed view hidden and inactive before it is first shown, so the click that shows it only unhides it", async () => {
    await show(false, <Counter label="a" />, true);
    await tick();
    await frames();
    expect(button()!.closest("[inert]")).not.toBeNull();
    expect(button()!.dataset.active).toBe("false");
    expect(mounts).toBe(1);
    const before = renders;
    await show(true, <Counter label="a" />, true);
    expect(renders).toBe(before);
    expect(button()!.closest("[inert]")).toBeNull();
    await settled();
    expect(button()!.dataset.active).toBe("true");
    expect(mounts).toBe(1);
  });

  it("draws a warmed view's first showing exactly as a cold first showing draws it", async () => {
    await show(true, <Counter label="b" />);
    await frames();
    const cold = host.innerHTML;
    act(() => root.unmount());
    root = createRoot(host);
    await show(false, <Counter label="a" />, true);
    await tick();
    await frames();
    await show(true, <Counter label="b" />, true);
    await settled();
    expect(host.innerHTML).toBe(cold);
  });

  it("hides a view in the click's own render without rendering it, and tells it it is inactive in a later transition", async () => {
    await show(true, <Counter label="a" />);
    await frames();
    const drawn = button()!.textContent, before = renders;
    const env = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };
    env.IS_REACT_ACT_ENVIRONMENT = false;
    try {
      flushSync(() => root.render(<Kept on={false}>{<Counter label="a" />}</Kept>));
      expect(renders).toBe(before);
      expect(button()!.closest("[inert]")).not.toBeNull();
    } finally {
      env.IS_REACT_ACT_ENVIRONMENT = true;
    }
    await settled();
    expect(button()!.dataset.active).toBe("false");
    expect(button()!.closest("[inert]")).not.toBeNull();
    expect(button()!.style.opacity).toBe("0");
    expect(button()!.textContent).toBe(drawn);
  });

  /** A view in three parts, the way the Kanban's columns are its parts. */
  const Parts = ({ label }: { label: string }) => <div data-warm-parts=""><section>{label}1</section><section>{label}2</section><section>{label}3</section></div>;
  const wrapper = (text: string) => [...host.querySelectorAll<HTMLElement>(".kept")].find((k) => k.textContent?.startsWith(text))!;

  it("lays a warmed view out one part a frame while it is hidden, then skips its rendering, drawing the same view throughout", async () => {
    await show(false, <Parts label="a" />, true);
    await tick();
    const drawn = wrapper("a").textContent, steps = [wrapper("a").dataset.warm];
    for (let i = 0; i < 6; i++) {
      await frame();
      steps.push(wrapper("a").dataset.warm);
      expect(wrapper("a").textContent).toBe(drawn);
    }
    expect(steps).toEqual(["0", "1", "2", "3", undefined, undefined, undefined]);
    expect(wrapper("a").hasAttribute("inert")).toBe(true);
  });

  it("waits for a warmed view whose code is still loading, then lays it out one part a frame", async () => {
    let arrive!: () => void;
    const Late = lazy(() => new Promise<{ default: typeof Parts }>((r) => (arrive = () => r({ default: Parts }))));
    await show(false, <Suspense fallback={null}><Late label="a" /></Suspense>, true);
    await tick();
    for (let i = 0; i < 3; i++) await frame();
    expect(host.querySelector<HTMLElement>(".kept")!.dataset.warm).toBe("0");
    await act(async () => arrive());
    const steps = [wrapper("a").dataset.warm];
    for (let i = 0; i < 5; i++) {
      await frame();
      steps.push(wrapper("a").dataset.warm);
    }
    expect(steps).toEqual(["0", "1", "2", "3", undefined, undefined]);
  });

  it("warms one view at a time, the next once the one ahead of it is laid out", async () => {
    await act(async () => root.render(<><Kept on={false} warm><Parts label="a" /></Kept><Kept on={false} warm><Parts label="b" /></Kept></>));
    await tick();
    expect(wrapper("a")).toBeDefined();
    expect(wrapper("b")).toBeUndefined();
    for (let i = 0; i < 4; i++) await frame();
    expect(wrapper("a").dataset.warm).toBeUndefined();
    expect(wrapper("b")).toBeUndefined();
    await frame();
    await frame();
    await tick();
    expect(wrapper("b").dataset.warm).toBe("0");
  });

  it("stops warming a view the moment it is shown", async () => {
    await show(false, <Parts label="a" />, true);
    await tick();
    await frame();
    expect(wrapper("a").dataset.warm).toBeDefined();
    await show(true, <Parts label="a" />, true);
    expect(wrapper("a").dataset.warm).toBeUndefined();
    expect(wrapper("a").hasAttribute("inert")).toBe(false);
  });
});
