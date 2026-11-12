// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Viewport, ViewportRow } from "./ViewportRows";

let host: HTMLDivElement, root: Root;
let notify: IntersectionObserverCallback;
let options: IntersectionObserverInit | undefined;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback, init?: IntersectionObserverInit) { notify = callback; options = init; }
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("viewport rows", () => {
  it("mounts contents inside the viewport plus overscan and unmounts them outside it", () => {
    act(() => root.render(
      <Viewport>
        <ViewportRow initial estimate={40}><span>first</span></ViewportRow>
        <ViewportRow initial={false} estimate={40}><span>second</span></ViewportRow>
      </Viewport>,
    ));
    const rows = [...host.querySelectorAll<HTMLElement>("[data-viewport-row]")];
    expect(options?.rootMargin).toBe("320px 0px");
    expect(host.textContent).toBe("first");

    act(() => notify([
      { target: rows[0], isIntersecting: false } as unknown as IntersectionObserverEntry,
      { target: rows[1], isIntersecting: true } as unknown as IntersectionObserverEntry,
    ], {} as IntersectionObserver));

    expect(host.textContent).toBe("second");
    expect(rows[0].style.minBlockSize).toBe("40px");
    expect(rows[1].style.minBlockSize).toBe("");
  });

  it("keeps an unmounted row at its last measured height so re-entering the overscan edge never resizes it", () => {
    const height = vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(82);
    act(() => root.render(
      <Viewport><ViewportRow initial estimate={96}><span>card</span></ViewportRow></Viewport>,
    ));
    const row = host.querySelector<HTMLElement>("[data-viewport-row]")!;
    const flip = (isIntersecting: boolean) => act(() => notify(
      [{ target: row, isIntersecting } as unknown as IntersectionObserverEntry], {} as IntersectionObserver));
    flip(false);
    expect(row.style.minBlockSize).toBe("82px");
    flip(true);
    flip(false);
    expect(row.style.minBlockSize).toBe("82px");
    height.mockRestore();
  });
});
