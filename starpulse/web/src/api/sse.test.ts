import { afterEach, describe, expect, it, vi } from "vitest";
import { hush } from "./sse";

describe("hush", () => {
  afterEach(() => vi.useRealTimers());

  it("leaves no timer behind once its subscription stops, even if a byte arrives after", () => {
    vi.useFakeTimers();
    const stop = new AbortController(), quiet = hush(stop.signal);

    stop.abort();
    quiet.heard();

    expect(vi.getTimerCount()).toBe(0);
  });
});
