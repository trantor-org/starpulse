import { describe, expect, it, vi } from "vitest";
import { whenShown } from "./shown";

describe("work only a shown canvas needs", () => {
  it("runs at once while shown", () => {
    const run = vi.fn(), w = whenShown(run);

    w.request();
    w.request();

    expect(run).toHaveBeenCalledTimes(2);
  });

  it("skips every request while hidden and runs once when shown again", () => {
    const run = vi.fn(), w = whenShown(run);
    w.show(false);

    w.request();
    w.request();
    expect(run).not.toHaveBeenCalled();
    w.show(true);

    expect(run).toHaveBeenCalledTimes(1);
  });

  it("runs nothing on show when nothing was skipped", () => {
    const run = vi.fn(), w = whenShown(run);
    w.show(false);
    w.show(true);

    expect(run).not.toHaveBeenCalled();
  });

  it("settles a skipped request on demand, once, while still hidden", () => {
    const run = vi.fn(), w = whenShown(run);
    w.show(false);
    w.request();

    w.settle();
    w.settle();

    expect(run).toHaveBeenCalledTimes(1);
  });
});
