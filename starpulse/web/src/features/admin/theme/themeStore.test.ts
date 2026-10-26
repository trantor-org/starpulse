import { describe, expect, it, vi } from "vitest";
import type { PrefStorage } from "../../../shared/nav";
import { BUILTIN, SLATE, build, type Pack } from "./scheme";
import { THEME_DEFAULTS, THEME_KEY, ThemeStore, loadTheme, type Tokens } from "./themeStore";

const memory = (): PrefStorage & { data: Map<string, string> } => {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
};
const off: PrefStorage = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };
const saved = (s: PrefStorage & { data: Map<string, string> }) => JSON.parse(s.data.get(THEME_KEY) ?? "null");

const custom: Pack = { name: "Mine", c: { a: "#112233" }, r: { ok: "a", run: "a", fail: "a", danger: "a", hold: "a", agent: "a", waits: "a", ready: "a", released: "a", phase: "a" } };

describe("theme store", () => {
  it("starts on StarPulse and Slate, and applies their tokens once", () => {
    const apply = vi.fn();
    const store = new ThemeStore(apply, memory());
    expect(store.get()).toEqual(THEME_DEFAULTS);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply.mock.calls[0][0]).toEqual(build(BUILTIN.starpulse, SLATE).t);
  });

  it("round-trips the pack, background, uploaded packs and backgrounds", () => {
    const s = memory();
    const first = new ThemeStore(() => {}, s);
    first.choosePack("nord");
    first.addPack(custom);
    first.addBg("Dusk", { ...SLATE, surface: "#2a1f3d" });
    const again = new ThemeStore(() => {}, s).get();
    expect(again.pack).toBe(first.get().pack);
    expect(again.bg).toBe(first.get().bg);
    expect(again.packs).toEqual(first.get().packs);
    expect(again.bgs).toEqual(first.get().bgs);
    expect(saved(s).pack).toBe(first.get().pack);
  });

  it("saves an imported pack with its background and switches to both", () => {
    const store = new ThemeStore(() => {}, memory());
    store.addPack(custom, { ...SLATE, surface: "#1f2a1f" });
    const { pack, bg, packs, bgs } = store.get();
    expect(packs.map((p) => p.pack.name)).toEqual(["Mine"]);
    expect(bgs.map((b) => b.id)).toEqual([bg]);
    expect(pack).toBe(packs[0].id);
  });

  it("loads the defaults for a malformed value", () => {
    const s = memory();
    s.setItem(THEME_KEY, "{not json");
    expect(loadTheme(s)).toEqual(THEME_DEFAULTS);
    expect(new ThemeStore(() => {}, s).get()).toEqual(THEME_DEFAULTS);
  });

  it("drops an unknown pack or background to its default", () => {
    const s = memory();
    s.setItem(THEME_KEY, JSON.stringify({ pack: "gone", bg: "gone", packs: [], bgs: [] }));
    expect(loadTheme(s)).toEqual(THEME_DEFAULTS);
  });

  it("falls back to the default when the active upload is deleted", () => {
    const store = new ThemeStore(() => {}, memory());
    store.addPack(custom, { ...SLATE, surface: "#1f2a1f" });
    const { pack, bg } = store.get();
    store.deletePack(pack);
    store.deleteBg(bg);
    expect(store.get().pack).toBe(THEME_DEFAULTS.pack);
    expect(store.get().bg).toBe(THEME_DEFAULTS.bg);
    expect(store.get().packs).toEqual([]);
  });

  it("redraws only when the pack or background changes", () => {
    const apply = vi.fn<(t: Tokens) => void>();
    const store = new ThemeStore(apply, memory());
    store.choosePack("starpulse");
    expect(apply).toHaveBeenCalledTimes(1);
    store.choosePack("nord");
    expect(apply).toHaveBeenCalledTimes(2);
  });

  it("keeps working when storage is denied", () => {
    const store = new ThemeStore(() => {}, off);
    expect(() => store.choosePack("nord")).not.toThrow();
    expect(store.get().pack).toBe("nord");
  });
});
