// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kept } from "../../shared/Kept";
import { ForwardingCard } from "./ForwardingCard";
import type { ForwardingStore } from "./forwarding";

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe("the Forwarding card in a view that is left", () => {
  it("stops asking the server for the status until the view is shown again", async () => {
    const load = vi.fn(async () => {});
    const view = { current: { configured: false }, phase: { kind: "idle" }, unavailable: "" };
    const store = { subscribe: () => () => {}, get: () => view, load } as unknown as ForwardingStore;
    const draw = (on: boolean) => act(async () => root.render(<Kept on={on}><ForwardingCard store={store} clock="24" /></Kept>));
    await draw(true);
    const shown = load.mock.calls.length;
    await draw(false);
    await act(async () => void vi.advanceTimersByTime(20_000));
    expect(load).toHaveBeenCalledTimes(shown);
    await draw(true);
    await act(async () => void vi.advanceTimersByTime(5_000));
    expect(load.mock.calls.length).toBeGreaterThan(shown);
  });
});
