// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { BgDialog } from "./BgDialog";
import { THEME_KEY, ThemeStore } from "./themeStore";
import { button, click, get, memory, mount, type } from "./testKit";

const TOMORROW_NIGHT = `scheme: "Tomorrow Night"
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
base0F: "a3685a"`;

let view: ReturnType<typeof mount>;
afterEach(() => view.unmount());

function open() {
  const storage = memory(), apply = vi.fn(), close = vi.fn();
  const theme = new ThemeStore(apply, storage);
  view = mount(<BgDialog theme={theme} close={close} />);
  return { storage, apply, close, theme, hex: (v: string) => type(get("input[aria-label='Surface hex']"), v) };
}

describe("BgDialog", () => {
  it("saves a background from #2a1f3d, applies it and closes", () => {
    const { hex, theme, apply, close } = open();
    hex("#2a1f3d");
    expect(get(".ramp")).toBeTruthy();
    click(button("Add and apply"));
    const s = theme.get();
    expect(s.bgs).toHaveLength(1);
    expect(s.bgs[0].n.surface).toBe("#2a1f3d");
    expect(s.bgs[0].name).toBe("Background #2a1f3d");
    expect(s.bg).toBe(s.bgs[0].id);
    expect(apply.mock.lastCall![0].surface).toBe("#2a1f3d");
    expect(close).toHaveBeenCalled();
  });

  it("starts on #2a1f3d so a click saves it", () => {
    const { theme } = open();
    click(button("Add and apply"));
    expect(theme.get().bgs[0].n.surface).toBe("#2a1f3d");
  });

  it("refuses #5a6b8c as too light and saves nothing", () => {
    const { hex, theme, storage, close } = open();
    hex("#5a6b8c");
    expect(get("[role=alert]").textContent).toContain("Backgrounds are dark only");
    const add = button("Add and apply");
    expect(add.disabled).toBe(true);
    click(add);
    expect(theme.get().bgs).toEqual([]);
    expect(storage.data.has(THEME_KEY)).toBe(false);
    expect(close).not.toHaveBeenCalled();
  });

  it("keeps the last good color while the hex is half typed", () => {
    const { hex, theme } = open();
    hex("#5a6b");
    click(button("Add and apply"));
    expect(theme.get().bgs[0].n.surface).toBe("#2a1f3d");
  });

  it("names the background as typed", () => {
    const { theme } = open();
    type(get("input[aria-label='Background name']"), "Plum");
    click(button("Add and apply"));
    expect(theme.get().bgs[0].name).toBe("Plum");
  });

  it("takes the ramp from base00-07 of a pasted scheme", () => {
    const { theme } = open();
    click(button("A scheme file"));
    type(get("textarea[aria-label='Scheme YAML']"), TOMORROW_NIGHT);
    click(button("Add and apply"));
    expect(theme.get().bgs[0]).toMatchObject({ name: "Tomorrow Night", n: { surface: "#1d1f21", ink: "#c5c8c6" } });
  });

  it("says Not read for a scheme file that is not one, and saves nothing", () => {
    const { theme } = open();
    click(button("A scheme file"));
    type(get("textarea"), "nothing here");
    expect(get("[role=alert]").textContent).toContain("Not read");
    expect(button("Add and apply").disabled).toBe(true);
    expect(theme.get().bgs).toEqual([]);
  });
});
