import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { staged } from "./staged";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("work split into tasks", () => {
  it("builds and applies in two later tasks, none in the caller's", () => {
    const log: string[] = [], later = staged();

    later(() => (log.push("build"), () => log.push("apply")));
    expect(log).toEqual([]);
    vi.advanceTimersToNextTimer();
    expect(log).toEqual(["build"]);
    vi.advanceTimersToNextTimer();

    expect(log).toEqual(["build", "apply"]);
  });

  it("drops an older chain a newer call overtakes, before and between its tasks", () => {
    const log: string[] = [], later = staged();

    later(() => (log.push("build 1"), () => log.push("apply 1")));
    later(() => (log.push("build 2"), () => log.push("apply 2")));
    vi.advanceTimersToNextTimer();
    later(() => (log.push("build 3"), () => log.push("apply 3")));
    vi.runAllTimers();

    expect(log).toEqual(["build 2", "build 3", "apply 3"]);
  });

  it("runs nothing once cancelled", () => {
    const run = vi.fn(), later = staged();

    later(() => run);
    later.cancel();
    vi.runAllTimers();

    expect(run).not.toHaveBeenCalled();
  });
});
