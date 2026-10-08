// @vitest-environment jsdom
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
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
    expect(button()!.dataset.label).toBe("b");
  });
});
