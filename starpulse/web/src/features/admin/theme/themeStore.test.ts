import { describe, expect, it, vi } from "vitest";
import { BUILTIN, SLATE, build, type Pack } from "./scheme";
import { server, saved } from "./testKit";
import { THEME_DEFAULTS, ThemeStore, loadTheme, type Tokens } from "./themeStore";

const settle = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

const custom: Pack = { name: "Mine", c: { a: "#112233" }, r: { ok: "a", run: "a", fail: "a", danger: "a", hold: "a", agent: "a", waits: "a", ready: "a", released: "a", phase: "a" } };

describe("theme store", () => {
  it("starts on StarPulse and Slate, and applies their tokens once", () => {
    const apply = vi.fn();
    const store = new ThemeStore(apply, server().fetcher);
    expect(store.get()).toEqual(THEME_DEFAULTS);
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply.mock.calls[0][0]).toEqual(build(BUILTIN.starpulse, SLATE).t);
  });

  it("sends the whole theme on each change, and another device adopts it as it was kept", () => {
    const s = server();
    const first = new ThemeStore(() => {}, s.fetcher);
    first.choosePack("nord");
    first.addPack(custom);
    first.addBg("Dusk", { ...SLATE, surface: "#2a1f3d" });
    const again = new ThemeStore(() => {}, s.fetcher);
    again.adopt({ theme: JSON.parse(JSON.stringify(saved(s))) });
    expect(again.get()).toEqual(first.get());
    expect(saved(s)).toEqual(first.get());
    expect(s.puts).toHaveLength(3);
  });

  it("draws an adopted theme without writing it back", () => {
    const s = server(), apply = vi.fn();
    const store = new ThemeStore(apply, s.fetcher);
    store.adopt({ theme: { ...THEME_DEFAULTS, pack: "nord" } });
    expect(store.get().pack).toBe("nord");
    expect(apply).toHaveBeenCalledTimes(2);
    expect(s.puts).toEqual([]);
  });

  it("saves an imported pack with its background and switches to both", () => {
    const store = new ThemeStore(() => {}, server().fetcher);
    store.addPack(custom, { ...SLATE, surface: "#1f2a1f" });
    const { pack, bg, packs, bgs } = store.get();
    expect(packs.map((p) => p.pack.name)).toEqual(["Mine"]);
    expect(bgs.map((b) => b.id)).toEqual([bg]);
    expect(pack).toBe(packs[0].id);
  });

  it("loads the defaults for a malformed value", () => {
    for (const raw of [undefined, null, "{not json", 7, []]) expect(loadTheme(raw)).toEqual(THEME_DEFAULTS);
  });

  it("drops an unknown pack or background to its default", () => {
    expect(loadTheme({ pack: "gone", bg: "gone", packs: [], bgs: [] })).toEqual(THEME_DEFAULTS);
  });

  it("falls back to the default when the active upload is deleted", () => {
    const store = new ThemeStore(() => {}, server().fetcher);
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
    const store = new ThemeStore(apply, server().fetcher);
    store.choosePack("starpulse");
    expect(apply).toHaveBeenCalledTimes(1);
    store.choosePack("nord");
    expect(apply).toHaveBeenCalledTimes(2);
  });

  it("says Saved once the server keeps a change", async () => {
    const store = new ThemeStore(() => {}, server().fetcher);
    store.choosePack("nord");
    await settle();
    expect(store.saved()).toEqual({ kind: "saved" });
  });

  it("names the server's reason when it refuses, and draws the theme the server holds", async () => {
    const apply = vi.fn<(t: Tokens) => void>();
    const fetcher = (async (_url: string, init?: { method?: string }) =>
      init?.method === "PUT" ? new Response(JSON.stringify({ error: "no such pack" }), { status: 400 }) : new Response(JSON.stringify({ theme: THEME_DEFAULTS }))) as never;
    const store = new ThemeStore(apply, fetcher);
    store.choosePack("nord");
    await settle();
    expect(store.saved()).toEqual({ kind: "refused", reason: "no such pack" });
    expect(store.get().pack).toBe(THEME_DEFAULTS.pack);
  });

  it("keeps working when the server does not answer", async () => {
    const store = new ThemeStore(() => {}, (async () => { throw new Error("offline"); }) as never);
    expect(() => store.choosePack("nord")).not.toThrow();
    await settle();
    expect(store.get().pack).toBe("nord");
    expect(store.saved()).toEqual({ kind: "refused", reason: "the server did not answer" });
  });
});
