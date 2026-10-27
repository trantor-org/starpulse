// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act } from "react";
import { ImportDialog } from "./ImportDialog";
import { build, fromBase16 } from "./scheme";
import { THEME_KEY, ThemeStore } from "./themeStore";
import { button, click, get, key, memory, mount, saved, type } from "./testKit";

const scheme = (b0 = "1d1f21", b0e = "b294bb") => `scheme: "Tomorrow Night"
author: "Chris Kempson"
base00: "${b0}"
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
base0E: "${b0e}"
base0F: "a3685a"`;
// base0E moved toward base0D: the closest status pair (ready and phase) is ΔE .029 apart on its own background.
const REFUSED = scheme("1d1f21", "939dc4");
const WARN = scheme("1d1f21", "9d9ac4");
// Light base00, so its background is refused while the pack alone is fine.
const LIGHT = scheme("e0e0e0");

let view: ReturnType<typeof mount>;
afterEach(() => view.unmount());

function open() {
  const storage = memory(), apply = vi.fn(), close = vi.fn();
  const theme = new ThemeStore(apply, storage);
  view = mount(<ImportDialog theme={theme} close={close} />);
  return { storage, apply, close, theme, paste: (text: string) => type(get("textarea[aria-label='Scheme YAML']"), text) };
}

describe("ImportDialog", () => {
  it("imports Tomorrow Night with its background, applies it and closes", () => {
    const { paste, theme, storage, apply, close } = open();
    paste(scheme());
    expect(get("[role=dialog]").textContent).toContain("DEMO-12");
    click(button("Import and apply"));
    const s = theme.get();
    expect(s.packs.map((p) => p.pack.name)).toEqual(["Tomorrow Night"]);
    expect(s.pack).toBe(s.packs[0].id);
    expect(s.bgs).toHaveLength(1);
    expect(s.bg).toBe(s.bgs[0].id);
    expect(saved(storage).packs[0].pack.src.label).toBe("Imported · Chris Kempson");
    const want = build(s.packs[0].pack, fromBase16(scheme()).bg).t;
    expect(apply.mock.lastCall![0]).toEqual(want);
    expect(close).toHaveBeenCalled();
  });

  it("refuses a scheme whose closest pair is under .035 apart, names the pair and saves nothing", () => {
    const { paste, theme, storage, close } = open();
    paste(REFUSED);
    const alert = get("[role=alert]");
    expect(alert.textContent).toContain("Not imported");
    expect(alert.textContent).toMatch(/ready and phase/);
    expect(alert.textContent).toContain("ΔE .029");
    const go = button("Import and apply");
    expect(go.disabled).toBe(true);
    click(go);
    expect(theme.get().packs).toEqual([]);
    expect(storage.data.has(THEME_KEY)).toBe(false);
    expect(close).not.toHaveBeenCalled();
  });

  it("warns, and still saves, a scheme between .035 and .05 apart", () => {
    const { paste, theme } = open();
    paste(WARN);
    const status = get("[role=status]");
    expect(status.textContent).toContain("Close pair");
    expect(status.textContent).toMatch(/waits on and ready/);
    expect(document.querySelector("[role=alert]")).toBeNull();
    click(button("Import and apply"));
    expect(theme.get().packs).toHaveLength(1);
  });

  it("says Not read for invalid YAML and saves nothing", () => {
    const { paste, theme, storage } = open();
    paste("base00: [unclosed\n  : : {");
    expect(get("[role=alert]").textContent).toContain("Not read");
    expect(get("[role=alert]").textContent).toMatch(/Not a base16 or base24 scheme/);
    expect(button("Import and apply").disabled).toBe(true);
    expect(theme.get().packs).toEqual([]);
    expect(storage.data.has(THEME_KEY)).toBe(false);
  });

  it("keeps Import off until there is text", () => {
    open();
    expect(button("Import and apply").disabled).toBe(true);
    expect(document.querySelector("[role=alert]")).toBeNull();
  });

  it("saves the pack under the name typed", () => {
    const { paste, theme } = open();
    paste(scheme());
    type(get("input[aria-label='Pack name']"), "  My night ");
    click(button("Import and apply"));
    expect(theme.get().packs[0].pack.name).toBe("My night");
    expect(theme.get().bgs[0].name).toBe("My night");
  });

  it("imports only the pack when the background box is cleared", () => {
    const { paste, theme } = open();
    paste(scheme());
    click(get("input[type=checkbox]"));
    click(button("Import and apply"));
    expect(theme.get().bgs).toEqual([]);
    expect(theme.get().bg).toBe("slate");
  });

  it("refuses a light scheme's background but imports its pack on the current one", () => {
    const { paste, theme } = open();
    paste(LIGHT);
    expect(get("input[type=checkbox]").hasAttribute("disabled")).toBe(true);
    expect(get(".note").textContent).toMatch(/Backgrounds are dark only/);
    click(button("Import and apply"));
    expect(theme.get().packs).toHaveLength(1);
    expect(theme.get().bgs).toEqual([]);
  });

  it("reads a picked file into the paste box", async () => {
    const { theme } = open();
    const input = get<HTMLInputElement>("input[type=file]");
    Object.defineProperty(input, "files", { value: [{ text: async () => scheme() }] });
    await act(async () => void input.dispatchEvent(new Event("change", { bubbles: true })));
    expect(get<HTMLTextAreaElement>("textarea").value).toContain("Tomorrow Night");
    click(button("Import and apply"));
    expect(theme.get().packs).toHaveLength(1);
  });

  it("closes on Cancel, on the backdrop and on Escape", () => {
    const { close } = open();
    click(button("Cancel"));
    click(get("#kbm"));
    key(get(".modal"), "Escape");
    expect(close).toHaveBeenCalledTimes(3);
  });
});
