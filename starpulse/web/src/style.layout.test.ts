import { describe, expect, it } from "vitest";
import css from "./style.css?raw";

const rule = (sel: string) => css.split("\n").find((l) => l.startsWith(`${sel} {`)) ?? "";

describe("the page's fixed layout", () => {
  it("pins the legend to the bottom of the right rail, whatever height Recent takes", () => {
    expect(rule("#legend")).toContain("margin-top: auto");
  });

  it("peeks a stack's edges uniformly: each the same step narrower and lower, each under the one above it", () => {
    const edge = css.slice(css.indexOf("#kb .stack > .edge {"), css.indexOf("}", css.indexOf("#kb .stack > .edge {")));
    expect(edge).toContain("left: calc((var(--i) + 1) * 6px)");
    expect(edge).toContain("right: calc((var(--i) + 1) * 6px)");
    expect(edge).toContain("bottom: calc(var(--peek) - (var(--i) + 1) * 5px)");
    expect(edge).toContain("z-index: calc(-1 - var(--i))");
  });
});

describe("the start question", () => {
  it("reuses the task modal's section heading and buttons rather than drawing its own", () => {
    expect(css).toMatch(/#kbm \.ask \.sh, #kbm \.tv \.sh \{/);
    expect(css).toMatch(/#kbm \.tvhead \.startbtn, #kbm \.ask \.startbtn \{/);
    expect(css).toMatch(/#kbm \.tv \.cancelbtn, #kbm \.tv \.savebtn, #kbm \.ask \.afoot \.manual, #kbm \.ask \.afoot \.cancel \{/);
    expect(css).not.toContain("#kbm .ask .afoot .startbtn {");
  });
});

describe("the DAGs view at a larger text size", () => {
  it("grows a row's step strip and its status star with the text", () => {
    expect(css).toContain("svg.dstrip:not(.big) { height: calc(20px * var(--fs)); }");
    expect(css).toMatch(/\.orb \{[^}]*width: calc\(11px \* var\(--fs\)\); height: calc\(11px \* var\(--fs\)\)/);
  });
});
