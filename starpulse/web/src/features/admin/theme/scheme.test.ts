import { describe, expect, it } from "vitest";
import { BUILTIN, DISTINCT, REFUSE_DE, ROLES, SLATE, WARN_DE, bgRefusal, build, closest, fromBase16, rampFrom, resolve } from "./scheme";
import { hex, lch } from "./color";

const HEX = /^#[0-9a-f]{6}$/;

const TOMORROW_NIGHT = `
scheme: "Tomorrow Night"
author: "Chris Kempson"
base00: "1d1f21"
base01: "282a2e"
base02: "373b41"
base03: "969896"
base04: "b4b7b4"
base05: "c5c8c6"
base06: "e0e0e0"
base07: "ffffff"
base08: "cc6666"
base09: "de935f"
base0A: "f0c674"
base0B: "b5bd68"
base0C: "8abeb7"
base0D: "81a2be"
base0E: "b294bb"
base0F: "a3685a"
`;

const BASE24 = `
name: "Test Base24"
base00: "101010"
base01: "202020"
base02: "303030"
base03: "808080"
base04: "a0a0a0"
base05: "c0c0c0"
base06: "e0e0e0"
base07: "ffffff"
base08: "ff5555"
base09: "ffaa55"
base0A: "ffff55"
base0B: "55ff55"
base0C: "55ffff"
base0D: "5599ff"
base0E: "ff55ff"
base0F: "aa5533"
base10: "401010"
base11: "104010"
base12: "ff8888"
base13: "ffdd88"
base14: "88ff88"
base15: "88ffff"
base16: "8888ff"
base17: "ff88ff"
`;

describe("built-in packs", () => {
  it("ships the nine packs and Slate", () => {
    expect(Object.keys(BUILTIN).sort()).toEqual(
      ["catppuccin", "everforest", "flexoki", "gruvbox", "nord", "rosepine", "solarized", "starpulse", "tokyonight"],
    );
    expect(Object.keys(SLATE).length).toBe(9);
  });

  for (const id of Object.keys(BUILTIN)) {
    it(`${id} resolves every role token on Slate`, () => {
      const { t } = build(BUILTIN[id], SLATE);
      for (const role of ROLES) {
        for (const key of [role, `${role}-hi`, `${role}-text`]) expect(t[key], key).toMatch(HEX);
      }
    });
  }

  it("resolves the neutral tokens for every pack on Slate", () => {
    const { t } = build(BUILTIN.starpulse, SLATE);
    for (const key of ["bg0", "bg1", "surface", "stack", "track", "faint", "muted", "ink-2", "ink", "ghost", "slate"]) {
      expect(t[key], key).toMatch(HEX);
    }
  });

  it("resolves a role's reference to a palette color or a mix", () => {
    expect(hex(resolve("#818cf8", {}))).toBe("#818cf8");
    expect(hex(resolve("blue", { blue: "#5599ff" }))).toBe("#5599ff");
  });
});

describe("fromBase16", () => {
  it("maps a base16 scheme to a named pack and a neutral ramp", () => {
    const { name, author, pack, bg } = fromBase16(TOMORROW_NIGHT);
    expect(name).toBe("Tomorrow Night");
    expect(author).toBe("Chris Kempson");
    expect(pack.c.base08).toBe("#cc6666");
    expect(Object.keys(pack.r)).toEqual(expect.arrayContaining(["ok", "run", "fail", "hold", "agent"]));
    expect(bg.surface).toBe("#1d1f21");
    for (const v of Object.values(bg)) expect(v).toMatch(HEX);
  });

  it("maps a base24 scheme, reading its name from the name field", () => {
    const { name, pack } = fromBase16(BASE24);
    expect(name).toBe("Test Base24");
    expect(pack.c.base08).toBe("#ff5555");
    expect(pack.c.base17).toBe("#ff88ff");
  });

  it("refuses a file that is not a base16 or base24 scheme", () => {
    expect(() => fromBase16("name: nothing\nbase00: \"000000\"")).toThrow(/Not a base16 or base24 scheme/);
  });
});

describe("the dE gate", () => {
  const spread = () => Object.fromEntries(DISTINCT.map((k, i) => [k, hex([0.7, 0.14, i * 40])])) as Record<string, string>;

  it("refuses two statuses closer than REFUSE_DE", () => {
    const t = spread();
    t.run = hex([lch(t.ok)[0] + 0.02, lch(t.ok)[1], lch(t.ok)[2]]);
    const [d, a, b] = closest(t);
    expect(d).toBeLessThan(REFUSE_DE);
    expect([a, b].sort()).toEqual(["ok", "run"]);
  });

  it("warns, but allows, two statuses between REFUSE_DE and WARN_DE", () => {
    const t = spread();
    t.run = hex([lch(t.ok)[0] + 0.042, lch(t.ok)[1], lch(t.ok)[2]]);
    const [d] = closest(t);
    expect(d).toBeGreaterThanOrEqual(REFUSE_DE);
    expect(d).toBeLessThan(WARN_DE);
  });

  it("passes statuses that are WARN_DE or further apart", () => {
    expect(closest(spread())[0]).toBeGreaterThanOrEqual(WARN_DE);
  });
});

describe("backgrounds", () => {
  it("builds a ramp from one picked color", () => {
    const n = rampFrom("#2a1f3d");
    expect(n.surface).toBe("#2a1f3d");
    expect(bgRefusal(n)).toBeNull();
  });

  it("refuses a light picked color as a background", () => {
    expect(bgRefusal(rampFrom("#5a6b8c"))).toMatch(/Backgrounds are dark only/);
  });
});
