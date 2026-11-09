import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ROLES, SLATE, build, BUILTIN } from "./scheme";
import { applyTheme, readTokens } from "./apply";

const root = () => {
  const vars = new Map<string, string>();
  return { vars, style: { setProperty: (k: string, v: string) => void vars.set(k, v), getPropertyValue: (k: string) => vars.get(k) ?? "" } };
};

describe("applyTheme", () => {
  let el: ReturnType<typeof root>;
  let events: number;
  beforeEach(() => {
    el = root();
    events = 0;
    vi.stubGlobal("document", { documentElement: { style: el.style } });
    vi.stubGlobal("window", { dispatchEvent: vi.fn(() => events++) });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("writes every role and neutral token onto :root", () => {
    const { t } = build(BUILTIN.nord, SLATE);
    applyTheme(t);
    for (const role of ROLES) {
      for (const key of [role, `${role}-hi`, `${role}-text`]) expect(el.vars.get(`--${key}`), key).toBe(t[key]);
    }
    for (const key of ["bg0", "surface", "ink", "ink-2", "ghost", "slate"]) expect(el.vars.get(`--${key}`), key).toBe(t[key]);
  });

  it("dispatches sp:theme once per change, and not for the same tokens", () => {
    const { t } = build(BUILTIN.tokyonight, SLATE);
    applyTheme(t);
    expect(window.dispatchEvent).toHaveBeenCalledTimes(1);
    applyTheme(t);
    expect(window.dispatchEvent).toHaveBeenCalledTimes(1);
    applyTheme({ ...t, ok: "#010203" });
    expect(window.dispatchEvent).toHaveBeenCalledTimes(2);
  });

  it("reads back the new values after applying them", () => {
    const { t } = build(BUILTIN.gruvbox, SLATE);
    applyTheme(t);
    expect(readTokens().ok).toBe(t.ok);
    expect(readTokens().surface).toBe(t.surface);
  });
});
