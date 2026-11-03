import { describe, expect, it } from "vitest";
import css from "./style.css?raw";

// TASK-8665 drew the In Progress drill-in as a 1440x900 frame under transform:scale(fit), in a position:fixed inset:0
// layer over the real shell, and every guard passed. A view lays out from its container; only a modal covers the page.

const views = import.meta.glob<string>(["./features/**/*.tsx", "./App.tsx", "!./**/*.test.tsx"], { query: "?raw", import: "default", eager: true });

const SCALE = /transform\s*:[^;}]*scale\(|transform\s*:\s*`[^`]*scale\(|\bscale\(\$\{/;
const FIXED_INLINE = /position\s*:\s*"fixed"[^}]*inset\s*:\s*0\b|inset\s*:\s*0\b[^}]*position\s*:\s*"fixed"/;
const MODAL = /role="(alert)?dialog"/;
// An empty scrim behind the phone sheets carries no content, so it has nothing to announce.
const SCRIMS = new Set(["#pn-scrim"]);

/** The ids of rules that pin a layer over the whole viewport. */
const fullScreenRules = (sheet: string) =>
  sheet.split("\n").filter((l) => !l.startsWith("@") && /position:\s*fixed/.test(l) && /inset:\s*0\b/.test(l)).map((l) => l.split(" {")[0].trim());

/** Violations in the style sheet and the view sources, one message each. */
export function viewViolations(sheet: string, sources: Record<string, string>): string[] {
  const out: string[] = [];
  for (const l of sheet.split("\n")) {
    if (!l.startsWith("@") && SCALE.test(l)) out.push(`style.css: transform scale in ${l.split(" {")[0].trim()}`);
  }
  for (const [file, src] of Object.entries(sources)) {
    if (SCALE.test(src)) out.push(`${file}: transform scale in a view`);
    if (FIXED_INLINE.test(src) && !/aria-modal="true"/.test(src)) out.push(`${file}: inline position:fixed inset:0 layer that is not a modal`);
    for (const sel of fullScreenRules(sheet).filter((s) => /^#[\w-]+$/.test(s) && !SCRIMS.has(s))) {
      if (src.includes(`id="${sel.slice(1)}"`) && !MODAL.test(src)) out.push(`${file}: ${sel} is a full-screen layer with no dialog role`);
    }
  }
  return out;
}

describe("view layout guard", () => {
  it("finds no view root under transform scale and no full-screen fixed layer that is not a modal dialog", () => {
    expect(Object.keys(views).length).toBeGreaterThan(10);
    expect(viewViolations(css, views)).toEqual([]);
  });

  it("refuses the pre-TASK-10613 drill-in: a fixed inset:0 overlay at 1440x900 scaled to the window", () => {
    const old = `<div role="dialog" className="suns-drill" style={{ position: "fixed", inset: 0, zIndex: 50 }}>
      <div style={{ width: W, height: H, transform: \`translate(-50%,-50%) scale(\${scale})\` }}>`;
    const found = viewViolations("", { "SunsDrillIn.tsx": old });
    expect(found).toContain("SunsDrillIn.tsx: transform scale in a view");
    expect(found).toContain("SunsDrillIn.tsx: inline position:fixed inset:0 layer that is not a modal");
  });

  it("refuses a full-screen fixed layer with no dialog role, and a scaled rule outside a keyframe", () => {
    const sheet = "#ovl { position: fixed; inset: 0; z-index: 9; }\n#v { transform: scale(.5); }\n@keyframes k { 0% { transform: scale(1); } }";
    const found = viewViolations(sheet, { "Ovl.tsx": '<div id="ovl" />' });
    expect(found).toEqual(["style.css: transform scale in #v", "Ovl.tsx: #ovl is a full-screen layer with no dialog role"]);
  });
});
