import { describe, expect, it } from "vitest";
import css from "./style.css?raw";

const rule = (sel: string) => css.split("\n").find((l) => l.startsWith(`${sel} {`)) ?? "";

describe("the page's fixed layout", () => {
  it("pins the legend to the bottom of the right rail, whatever height Recent takes", () => {
    expect(rule("#legend")).toContain("margin-top: auto");
  });

  it("paints the Star Map canvas between the navigator and the rail before the renderer sizes it, so the first load shifts nothing", () => {
    expect(rule("#c")).toContain("left: var(--nav)");
    expect(rule("#c")).toContain("right: var(--rail)");
    expect(rule("#c")).toContain("height: 100%");
  });

  it("collapses the navigator and rail under a phone-width viewport, so the canvas keeps a positive width", () => {
    const at = css.indexOf("@media (max-width: 900px) {");
    expect(at).toBeGreaterThan(-1);
    const phone = css.slice(at, css.indexOf("\n}", at));
    expect(phone).toContain("--nav: 0px");
    expect(phone).toContain("--rail: 0px");
    expect(phone).toMatch(/#nav, #rail \{ display: none/);
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

  it("keeps a column's header its height when a chain lights its badge, whatever font draws the chain glyph", () => {
    expect(block("#kb .col h2 .cc")).toContain("line-height: 0");
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

describe("the Admin view's Autopilot card", () => {
  it("wraps the next pick's reason under a long title and sets its meters two to a row, so a larger text size grows the card instead of clipping it", () => {
    expect(rule("#admin .ap .nx")).toContain("flex-wrap: wrap");
    expect(rule("#admin .ap .dims")).toContain("repeat(2, minmax(0, 1fr))");
    expect(css).not.toContain("#kb .ap");
  });

  it("dims the meters and the count in flight while paused", () => {
    expect(rule("#admin .ap.off :is(.dims, .inflight)")).toContain("opacity: .45");
  });
});

describe("the status dot", () => {
  it("pulses while the stream is down and coming back, and holds still under reduced motion", () => {
    expect(rule("#nav .dot.wait")).toContain("animation: ap-go");
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{ #nav \.dot\.wait \{ animation: none; \} \}/);
  });

  it("glows red once the stream is lost, as it glows green when live", () => {
    expect(css).toMatch(/#nav \.dot\.off \{[^}]*box-shadow: 0 0 8px var\(--fail\)/);
  });
});

describe("the Admin page at phone width", () => {
  it("lets a long Next batch value break and the grid cell shrink, so the row holds it", () => {
    const phone = css.slice(css.lastIndexOf("@media (max-width: 900px)"));
    expect(phone).toMatch(/#admin \.row\.fw-block > \* \{[^}]*min-width: 0/);
    expect(phone).toMatch(/#admin \.fw-next li \{[^}]*overflow-wrap: anywhere/);
  });
});

describe("the Kanban Start session dialog at phone width", () => {
  const phone = css.slice(css.lastIndexOf("@media (max-width: 900px)"));

  it("takes the page's side margins and lets its answers wrap onto a second row, so none ends past the screen", () => {
    expect(phone).toMatch(/#kbm \.modal\.ask \{[^}]*width: calc\(100vw - 2 \* var\(--pm\)\)/);
    expect(phone).toMatch(/#kbm \.ask \.afoot \{[^}]*flex-wrap: wrap/);
  });

  it("tightens its padding, grid gap and choice buttons and lifts the 80vh cap, so the label/value grid and every answer fit the screen at the largest text size", () => {
    expect(phone).toMatch(/#kbm \.modal\.ask \{[^}]*max-height: calc\(100dvh - 2 \* var\(--pm\)\)/);
    expect(phone).toMatch(/#kbm \.ask \.opt \{[^}]*column-gap: 10px/);
    expect(phone).toMatch(/#kbm \.ask \.seg button \{[^}]*padding: 2px 9px/);
    expect(rule("#kbm .ask .opt")).toContain("grid-template-columns: max-content minmax(0, 1fr)");
  });

  it("keeps the desktop dialog as it was: 560px, its answers on one row", () => {
    expect(rule("#kbm .modal.ask")).toContain("width: min(560px, calc(100vw - 40px))");
    expect(rule("#kbm .ask .afoot")).not.toContain("flex-wrap");
  });
});
