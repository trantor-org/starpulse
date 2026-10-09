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

describe("switching views under load", () => {
  const block = (sel: string) => css.slice(css.indexOf(`${sel} {`), css.indexOf("}", css.indexOf(`${sel} {`)));

  it("draws the navigator and rail as flat glass: a backdrop blur recomposites both on every frame of a switch", () => {
    expect(block("aside")).toContain("background:");
    expect(block("aside")).not.toContain("backdrop-filter");
  });

  it("skips the Kanban cards and DAG rows scrolled out of sight, so showing either view styles and paints only what is on screen", () => {
    expect(css).toMatch(/#kb \.card \{[^}]*content-visibility: auto; contain-intrinsic-size: auto \d+px/);
    expect(css).toMatch(/#dg \.trow \{[^}]*content-visibility: auto; contain-intrinsic-size: auto \d+px/);
  });

  it("keeps a Kanban column's width when its scrollbar comes and goes, as an unstacked stack overflows it", () => {
    expect(block("#kb .col .body")).toContain("scrollbar-gutter: stable");
  });

  it("takes a scrolling column's cards out of hit-testing, so cards passing under a still pointer do not hover", () => {
    expect(block("#kb .col .body.scrolling .card")).toContain("pointer-events: none");
  });

  it("keeps the navigator search's Matches as wide when they overflow as when they fit, and takes a scrolling list's rows out of hit-testing", () => {
    expect(block("#nav .matches")).toContain("scrollbar-gutter: stable");
    expect(block("#nav .matches.scrolling .hit")).toContain("pointer-events: none");
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

describe("the DAGs view at rest", () => {
  it("streams links only in the row the pointer, keyboard or a Recent line rests on and in the open DAG's chart: stroke-dashoffset repaints every frame", () => {
    const streams = css.split("\n").filter((l) => l.includes("animation: dag-stream"));
    expect(streams).toEqual([
      "@media (prefers-reduced-motion: no-preference) { .kept:not([inert]) #dg :is(.trow:is(:hover, .spot, :focus-visible), .dgm) svg.dstrip path.link { animation: dag-stream .42s linear infinite; } }",
    ]);
  });
});
