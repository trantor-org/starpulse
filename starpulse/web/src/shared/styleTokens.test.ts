// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync(new URL("../style.css", import.meta.url), "utf8");
const sheet = readFileSync(new URL("../../../../design/elements/index.html", import.meta.url), "utf8");

const NAMED = "white|black|red|green|blue|yellow|orange|purple|pink|gray|grey|silver|gold|cyan|magenta|lime|teal|navy|maroon|olive|aqua|fuchsia|brown|tan|violet|indigo|salmon|coral|crimson|khaki|plum|orchid|turquoise|azure|beige|ivory|lavender|tomato";
const LITERAL = new RegExp(
  `#[0-9a-f]{3,8}\\b|%23[0-9a-f]{3,8}\\b|\\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\\(|\\b(?:${NAMED})\\b`,
  "gi",
);

/** The `:root` blocks, which are where the palette is declared. */
function withoutTokenBlock(css: string): string {
  let out = "";
  let i = 0;
  for (;;) {
    const at = css.indexOf(":root", i);
    if (at < 0) return out + css.slice(i);
    out += css.slice(i, at);
    let depth = 0;
    let j = css.indexOf("{", at);
    for (; j < css.length; j++) {
      if (css[j] === "{") depth++;
      else if (css[j] === "}" && --depth === 0) break;
    }
    i = j + 1;
  }
}

/** Every color literal a declaration draws with outside the token block: selectors, at-rule preludes and comments are not declarations. */
function colorLiterals(css: string): string[] {
  const found: string[] = [];
  const rest = withoutTokenBlock(css).replace(/\/\*[\s\S]*?\*\//g, "");
  for (const m of rest.matchAll(/[^{};]*[{};]/g)) {
    const segment = m[0];
    if (segment.endsWith("{")) continue; // a selector or an at-rule prelude
    const colon = segment.indexOf(":");
    if (colon < 0) continue;
    const value = segment.slice(colon + 1).replace(/var\(--[\w-]+/g, "var(");
    found.push(...(value.match(LITERAL) ?? []));
  }
  return found;
}

describe("style.css palette", () => {
  it("draws every color from a :root token", () => {
    expect(colorLiterals(styles)).toEqual([]);
  });
});

/** The element sheet's own styling: its style blocks and every inline style attribute, as stylesheet text. */
function sheetCss(html: string): string {
  const blocks = [...html.matchAll(/<style>([\s\S]*?)<\/style>/g)].map((m) => m[1]);
  const inline = [...html.matchAll(/ style="([^"]*)"/g)].map((m) => `x { ${m[1]} }`);
  return [...blocks, ...inline].join("\n");
}

describe("design/elements palette", () => {
  it("draws every color of its own layout from a token", () => {
    expect(sheetCss(sheet)).toContain("var(--slate)"); // the scan reads the sheet's styling rather than nothing
    expect(colorLiterals(sheetCss(sheet))).toEqual([]);
  });

  it("links the real stylesheet rather than carrying a copy", () => {
    expect(sheet).toContain('href="../../starpulse/web/src/style.css"');
  });
});

describe("colorLiterals", () => {
  it("flags hex, rgb(a), named colors and an encoded hex in a data URI", () => {
    const css = `a { color: #fbbf24; background: rgba(1,2,3,.5); border: 1px solid white;
      background-image: url("data:image/svg+xml,%3Cpath stroke='%236ee7b7'/%3E"); }`;
    expect(colorLiterals(css)).toEqual(["#fbbf24", "rgba(", "white", "%236ee7b7"]);
  });

  it("flags a literal inside a media query and a keyframe", () => {
    expect(colorLiterals("@media (x) { a { color: #fff; } } @keyframes k { from { background: rgb(0 0 0); } }")).toEqual(["#fff", "rgb("]);
  });

  it("flags a literal used as a var() fallback", () => {
    expect(colorLiterals("a { color: var(--violet, #a78bfa); }")).toEqual(["#a78bfa"]);
  });

  it("lets tokens, mixes of tokens, transparent and currentColor through", () => {
    const css = "a { color: var(--ok); border-color: color-mix(in srgb, var(--slate) 18%, transparent); box-shadow: 0 0 8px currentColor; background: var(--white); }";
    expect(colorLiterals(css)).toEqual([]);
  });

  it("does not read an id selector, white-space or a comment as a color", () => {
    const css = "/* #fff white */ #efa { white-space: nowrap; } #feed b { font-weight: 400; }";
    expect(colorLiterals(css)).toEqual([]);
  });

  it("allows literals inside :root, braces and all", () => {
    expect(colorLiterals(":root { --ok: #34d399; --fs: 1; } a { color: var(--ok); }")).toEqual([]);
  });
});
