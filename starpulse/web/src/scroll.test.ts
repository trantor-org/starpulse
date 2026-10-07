import { describe, expect, it } from "vitest";
import sheet from "./style.css?raw";

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
    for (const box of ["#kb .col .body", "#nav .layers", "#panel", "#admin", "#feed"]) expect(rule.sel).toContain(box);
  });

  it("wrap a Kanban card's head and its pull request chip in a narrow lane rather than clip them", () => {
    for (const sel of ["#kb .card .top", "#kb .pr"]) {
      const r = rules.find((x) => x.sel === sel);
      expect(r?.body, sel).toMatch(/flex-wrap:\s*wrap/);
    }
    expect(rules.find((x) => x.sel === "#kb .pr")?.body).toMatch(/max-width:\s*100%/);
  });

  it("wrap the Kanban toolbar onto a second row rather than run it under the right rail", () => {
    const bar = rules.find((x) => x.sel === "#kb .filters")!.body;
    expect(bar).toMatch(/flex-wrap:\s*wrap/);
    expect(bar).not.toMatch(/(^|;)\s*height:/);
  });

  it("leave the right rail's text whole: its recent moves and legend wrap, and none is cut to an ellipsis", () => {
    const rail = rules.filter((r) => /#feed|#legend/.test(r.sel));
    expect(rail.length).toBeGreaterThan(0);
    for (const r of rail) expect(r.body, r.sel).not.toMatch(/text-overflow|white-space:\s*nowrap|overflow:\s*hidden/);
  });
});
