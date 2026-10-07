// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

// the canvas renderer needs a browser's 2D context; the navigator around it does not
vi.mock("./renderer", () => ({
  renderer: () => new Proxy({}, { get: () => () => {} }),
}));

let host: HTMLDivElement, root: Root;
const type = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const clear = () => host.querySelector<HTMLButtonElement>('#nav button[aria-label="Clear the search"]');

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  await act(async () => root.render(<App />));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the navigator's Star Map entry", () => {
  it("draws the orbit icon, a planet, a tilted orbit and a moon, in place of the bare ring", () => {
    const glyph = host.querySelector("#nav section.views .node i.g")!;

    expect(glyph.querySelectorAll("circle")).toHaveLength(2);
    expect(glyph.querySelector("ellipse")?.getAttribute("transform")).toBe("rotate(-28 12 12)");
    expect(glyph.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 24 24");
  });
});

describe("the navigator search's clear button", () => {
  it("draws one ✕ only while the search holds text, and a click empties it and keeps the focus", () => {
    const input = host.querySelector<HTMLInputElement>("#q")!;

    expect(clear()).toBeNull();
    type(input, "needle");
    expect(host.querySelectorAll('#nav button[aria-label="Clear the search"]')).toHaveLength(1);

    const press = new MouseEvent("mousedown", { bubbles: true, cancelable: true });
    act(() => void clear()!.dispatchEvent(press));
    act(() => clear()!.click());

    expect(press.defaultPrevented).toBe(true);
    expect(input.value).toBe("");
    expect(document.activeElement).toBe(input);
    expect(clear()).toBeNull();
  });
});

describe("the navigator's search slot", () => {
  const remount = async (view: string, folded: boolean) => {
    act(() => root.unmount());
    localStorage.setItem("fv.nav.folded", folded ? "1" : "0");
    history.replaceState(null, "", `/?view=${view}`);
    root = createRoot(host);
    await act(async () => root.render(<App />));
  };
  const mag = () => host.querySelector<HTMLButtonElement>("#nv-mag");

  it("holds the Kanban search while the Kanban is open, under the Views and out of the toolbar", async () => {
    await remount("kanban", false);

    expect(host.querySelector("#nav #kbq")).not.toBeNull();
    expect(host.querySelector("#kb .filters #kbq")).toBeNull();
    expect(host.querySelector("#nav #q")).toBeNull();
  });

  it.each([
    ["constellation", "#q", "Star Map"],
    ["kanban", "#kbq", "Kanban"],
  ])("unfolds the navigator and focuses the %s search from the folded strip's magnifier", async (view, input, name) => {
    await remount(view, true);
    expect(host.querySelector("#nav")!.classList.contains("folded")).toBe(true);
    expect(mag()!.title).toBe(`Search the ${name}`);

    act(() => mag()!.click());

    expect(host.querySelector("#nav")!.classList.contains("folded")).toBe(false);
    expect(document.activeElement).toBe(host.querySelector(input));
  });

  it.each([
    ["constellation", "#q", "Star Map"],
    ["kanban", "#kbq", "Kanban"],
  ])("lights the %s magnifier, with a dot and the query in its title, only while that search holds one", async (view, input, name) => {
    await remount(view, true);
    const search = host.querySelector<HTMLInputElement>(input)!;
    expect(mag()!.classList.contains("set")).toBe(false);

    type(search, "needle");
    expect(mag()!.classList.contains("set")).toBe(true);
    expect(mag()!.title).toBe(`Search the ${name} (filtering: needle)`);

    type(search, "");
    expect(mag()!.classList.contains("set")).toBe(false);
    expect(mag()!.title).toBe(`Search the ${name}`);
  });
});
