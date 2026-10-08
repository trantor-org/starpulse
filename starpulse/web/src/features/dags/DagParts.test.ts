// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { labelPx } from "./DagParts";

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.style.removeProperty("--fs");
});

describe("labelPx", () => {
  it("scales the chart's base size by the Admin's text scale without asking for computed style", () => {
    const computed = vi.spyOn(window, "getComputedStyle");
    expect(labelPx()).toBeCloseTo(6.1);
    document.documentElement.style.setProperty("--fs", "1.3");
    expect(labelPx()).toBeCloseTo(6.1 * 1.3);
    expect(computed).not.toHaveBeenCalled();
  });
});
