// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { IdleCells, Orb, RunCells, StepStar, labelPx } from "./DagParts";
import type { DagFacts, Row } from "./dagsModel";
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

describe("StepStar", () => {
  it("draws a step with no run behind it in the slate, not the Star Map's near-black track, so an Idle row's strip reads", () => {
    const html = renderToStaticMarkup(createElement("svg", null, createElement(StepStar, { x: 5, y: 5, r: 4, status: "not_started" })));
    expect(html).toContain('stroke="var(--slate)"');
    expect(html).toContain('stroke-opacity="0.8"');
    expect(html).not.toContain(DAG_COLOR.not_started);
  });
});

describe("row cells", () => {
  const row = (r: Partial<Row>) => ({ phase: "idle", steps: {}, ...r, d: { name: "x", status: "succeeded" } }) as unknown as Row;
  const text = (el: ReturnType<typeof createElement>) => renderToStaticMarkup(el).replace(/<[^>]+>/g, "|").replace(/\|+/g, "|");
  it("gives a running row its elapsed time, then steps done and running", () => {
    const r = row({ phase: "running", startedAt: 1000, steps: { a: "succeeded", b: "running", c: "not_started" } });
    expect(text(createElement(RunCells, { r, now: 1060 }))).toBe("|1m 0s|1/3 done| · 1 running|");
  });
  it("gives a queued row a waiting elapsed cell and a queued progress cell", () => {
    expect(text(createElement(RunCells, { r: row({ phase: "queued", steps: { a: "not_started" } }), now: 0 }))).toBe("|waiting|queued|");
  });
  it("gives an Idle row its last result, runs a week and p95 with its failure share", () => {
    const f = { runs: 12, p95Seconds: 90, failureShare: 0.25 } as DagFacts;
    const out = text(createElement(IdleCells, { r: row({ phase: "ok", finishedAt: 1000 }), f, now: 4000 }));
    expect(out).toContain("50m ago");
    expect(out).toContain("12");
    expect(out).toContain("p95 1m 30s");
    expect(out).toContain("25% fail");
  });
});
