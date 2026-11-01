// The drill-in's motion: every animation the Suns engine names plays from a keyframe the page defines, under a name no other view's keyframe shares.
import { describe, expect, it } from "vitest";
import css from "../../style.css?raw";
import engine from "./sunsEngine.js?raw";

const named = [...new Set([...engine.matchAll(/animation:([a-z-]+) /g)].map((m) => m[1]))];

describe("the drill-in's animations", () => {
  it("names the engine's breathing suns, marching flows, pulsing nodes and twinkling stars", () => {
    expect(named.sort()).toEqual(["sd-breathe", "sd-march", "sd-orbit", "sd-pulse", "sd-twinkle"]);
  });

  it("defines a keyframe for each, so each one plays", () => {
    for (const name of named) expect(css).toContain(`@keyframes ${name} {`);
  });

  it("stills them for a reader who asks for reduced motion", () => {
    const at = css.indexOf("@media (prefers-reduced-motion: reduce)");
    expect(css.slice(at)).toMatch(/#sd [^{]*\{[^}]*animation: none/);
  });
});
