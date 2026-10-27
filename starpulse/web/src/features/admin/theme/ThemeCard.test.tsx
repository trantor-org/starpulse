// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeCard } from "./ThemeCard";
import { BUILTIN, SLATE, type Pack } from "./scheme";
import { ThemeStore } from "./themeStore";
import { button, click, get, key, memory, mount, saved, type } from "./testKit";

const mine: Pack = { ...BUILTIN.nord, name: "Mine", src: { label: "Imported" } };

let view: ReturnType<typeof mount>;
afterEach(() => view.unmount());

function open() {
  const storage = memory(), apply = vi.fn();
  const theme = new ThemeStore(apply, storage);
  theme.addPack(mine, { ...SLATE, surface: "#2a1f3d" });
  view = mount(<ThemeCard theme={theme} />);
  const own = (name: string) => [...document.querySelectorAll<HTMLElement>(".own")].find((o) => o.textContent?.includes(name))!;
  return { storage, apply, theme, own };
}

describe("ThemeCard uploads", () => {
  it("lists an imported pack and background as Own tiles with Rename and Delete", () => {
    const { own } = open();
    expect(document.querySelectorAll(".own")).toHaveLength(2);
    expect([...own("Mine").querySelectorAll(".acts button")].map((b) => b.textContent)).toEqual(["Rename", "Delete"]);
    expect(document.querySelectorAll(".tile.on")).toHaveLength(2);
  });

  it("draws a vibe line only for a pack that has one", () => {
    const theme = new ThemeStore(vi.fn(), memory());
    theme.addPack({ ...mine, vibe: undefined });
    view = mount(<ThemeCard theme={theme} />);
    expect(document.querySelectorAll(".own")).toHaveLength(1);
    expect(document.querySelectorAll(".own .vibe")).toHaveLength(0);
    expect(document.querySelectorAll(".tile .vibe").length).toBe(Object.keys(BUILTIN).length);
  });

  it("opens the import and background dialogs from the add tiles", () => {
    open();
    click(button("+Import schemebase16 or base24 YAML"));
    expect(get("[role=dialog]").getAttribute("aria-label")).toBe("Import a color scheme");
    click(button("Cancel"));
    expect(document.querySelector("[role=dialog]")).toBeNull();
    click(button("+Add backgroundfrom one color or a scheme"));
    expect(get("[role=dialog]").getAttribute("aria-label")).toBe("Add a background");
  });

  it("renames a tile in sp.theme and on the page", () => {
    const { own, storage } = open();
    click(button("Rename", own("Mine")));
    const field = get<HTMLInputElement>("input.ren");
    type(field, "Dusk");
    key(field, "Enter");
    expect(saved(storage).packs[0].pack.name).toBe("Dusk");
    expect(saved(storage).bgs[0].name).toBe("Mine");
    expect(document.querySelector("input.ren")).toBeNull();
    expect(own("Dusk")).toBeTruthy();
  });

  it("renames a background", () => {
    const { storage } = open();
    click(button("Rename", get(".bgs .own")));
    const field = get<HTMLInputElement>("input.ren");
    type(field, "Plum");
    key(field, "Enter");
    expect(saved(storage).bgs[0].name).toBe("Plum");
  });

  it("keeps the name on Escape", () => {
    const { own, storage } = open();
    click(button("Rename", own("Mine")));
    const field = get<HTMLInputElement>("input.ren");
    type(field, "Dusk");
    key(field, "Escape");
    expect(saved(storage).packs[0].pack.name).toBe("Mine");
  });

  it("keeps the name when the new one is blank", () => {
    const { own, storage } = open();
    click(button("Rename", own("Mine")));
    const field = get<HTMLInputElement>("input.ren");
    type(field, "   ");
    key(field, "Enter");
    expect(saved(storage).packs[0].pack.name).toBe("Mine");
  });

  it("asks before deleting, and Keep leaves it", () => {
    const { own, theme } = open();
    click(button("Delete", own("Mine")));
    expect(get("[role=group]").getAttribute("aria-label")).toBe("Delete Mine?");
    expect(theme.get().packs).toHaveLength(1);
    click(button("Keep"));
    expect(theme.get().packs).toHaveLength(1);
    expect(document.querySelector("[role=group]")).toBeNull();
  });

  it("falls back to StarPulse when the active scheme is deleted", () => {
    const { own, theme, storage } = open();
    expect(theme.get().pack).not.toBe("starpulse");
    click(button("Delete", own("Mine")));
    click(button("Delete", get("[role=group]")));
    expect(theme.get().pack).toBe("starpulse");
    expect(saved(storage)).toMatchObject({ pack: "starpulse", packs: [] });
    expect(document.querySelectorAll(".own")).toHaveLength(1);
  });

  it("falls back to Slate when the active background is deleted", () => {
    const { theme, storage } = open();
    click(button("Delete", get(".bgs .own")));
    click(button("Delete", get("[role=group]")));
    expect(theme.get().bg).toBe("slate");
    expect(saved(storage)).toMatchObject({ bg: "slate", bgs: [] });
  });
});
