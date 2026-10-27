// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { Orb, labelPx } from "./DagParts";
import { DAG_COLOR, MUTED } from "../../render/draw";

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

describe("Orb", () => {
  const html = (phase: Parameters<typeof Orb>[0]["phase"]) => renderToStaticMarkup(createElement(Orb, { phase }));
  it("draws the Star Map orbiter: a turning arc while running, grey while queued, a dashed red ring when failed", () => {
    expect(html("running")).toContain('class="spin"');
    expect(html("queued")).toContain(`stroke="${MUTED}"`);
    expect(html("queued")).not.toContain("spin");
    expect(html("failed")).toContain('class="fail-ring"');
    expect(html("failed")).toContain(`stroke="${DAG_COLOR.failed}"`);
    expect(html("ok")).not.toMatch(/spin|fail-ring/);
  });
});
