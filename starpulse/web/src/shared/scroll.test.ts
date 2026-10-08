import { describe, expect, it } from "vitest";
import sheet from "../style.css?raw";

const css = sheet.replace(/\/\*[\s\S]*?\*\//g, "");
const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => ({ sel: m[1].trim(), body: m[2] }));
const scrolls = (body: string) => /overflow(-[xy])?\s*:\s*(auto|scroll)/.test(body);

describe("the page's scrolling boxes", () => {
  it("scroll in one rule only: vertically, never sideways, with the Kanban columns' thin scrollbar", () => {
    const scrolling = rules.filter((r) => scrolls(r.body));
    expect(scrolling.map((r) => r.sel)).toHaveLength(1);
    const [rule] = scrolling;
    expect(rule.body).toMatch(/overflow-x:\s*hidden/);
    expect(rule.body).toMatch(/overflow-y:\s*auto/);
    expect(rule.body).toMatch(/scrollbar-width:\s*thin/);
    expect(rule.body).toMatch(/scrollbar-color:\s*color-mix\(in srgb, var\(--slate\) 25%, transparent\) transparent/);
    for (const box of ["#kb .col .body", "#nav .matches", "#panel", "#admin", "#dg #catalog"]) expect(rule.sel).toContain(box);
    expect(rule.sel).not.toContain("#feed");
  });

  it("wrap a Kanban card's head and its pull request chip in a narrow lane rather than clip them", () => {
    for (const sel of ["#kb .card .top", "#kb .pr"]) {
      const r = rules.find((x) => x.sel === sel);
      expect(r?.body, sel).toMatch(/flex-wrap:\s*wrap/);
    }
    expect(rules.find((x) => x.sel === "#kb .pr")?.body).toMatch(/max-width:\s*100%/);
  });

  it("wrap the Kanban and DAGs toolbar onto a second row rather than run it under the right rail", () => {
    const bar = rules.find((x) => x.sel === ":is(#kb, #dg) .filters")!.body;
    expect(bar).toMatch(/flex-wrap:\s*wrap/);
    expect(bar).not.toMatch(/(^|;)\s*height:/);
  });

  it("keep the right rail's Recent lines to one line each, cut with an ellipsis in a box that never scrolls, and leave the legend whole", () => {
    const body = (sel: string) => rules.find((r) => r.sel === sel)!.body;
    expect(body("#rail .recent")).toMatch(/height:\s*50%/);
    expect(body("#feed")).toMatch(/overflow:\s*hidden/);
    expect(body("#feed div")).toMatch(/white-space:\s*nowrap/);
    expect(body("#feed div")).toMatch(/text-overflow:\s*ellipsis/);
    const legend = rules.filter((r) => /#legend/.test(r.sel));
    expect(legend.length).toBeGreaterThan(0);
    for (const r of legend) expect(r.body, r.sel).not.toMatch(/text-overflow|white-space:\s*nowrap|overflow:\s*hidden/);
  });
});
