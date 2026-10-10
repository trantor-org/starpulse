// @vitest-environment jsdom
// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
// @ts-expect-error Same Node-only import: jsdom swaps the global URL for one readFileSync refuses.
import { URL as NodeURL } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOARD_DRAWN } from "./shared/boardMark";

const made = vi.hoisted(() => ({ renderers: 0, spy: {} as Record<string, ReturnType<typeof vi.fn>> }));
vi.mock("./render/renderer", () => ({
  renderer: () => {
    made.renderers++;
    made.spy = { start: vi.fn(), stop: vi.fn(), show: vi.fn(), refresh: vi.fn() };
    return made.spy;
  },
}));
vi.mock("./lazyViews", () => ({
  Kanban: () => <div id="kb" />,
  Dags: () => <div id="dg" />,
  AdminPage: () => <div id="admin" />,
  OrbitCard: () => <div id="og" />,
  prefetchViews: () => () => {},
}));

const page = readFileSync(new NodeURL("../index.html", import.meta.url), "utf8");
const frames = page.slice(page.indexOf("<body>") + 6, page.indexOf('<script type="module"'));

let root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetModules();
  made.renderers = 0;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  history.replaceState(null, "", "/?view=constellation");
  document.body.innerHTML = frames;
  performance.mark(BOARD_DRAWN); // the page mounts after its first frame
});
afterEach(() => {
  act(() => root.unmount());
  document.body.innerHTML = "";
  performance.clearMarks(BOARD_DRAWN);
  vi.unstubAllGlobals();
});

describe("the page mounted over a booted renderer", () => {
  it("adopts the booted renderer, canvas and store instead of making its own, and leaves it running when it unmounts", async () => {
    const { boot } = await import("./boot");
    const { App } = await import("./App");
    const held = boot(vi.fn());
    const canvas = document.getElementById("c");
    root = createRoot(document.getElementById("root")!);

    await act(async () => root.render(<App />));

    expect(made.renderers).toBe(1);
    expect(made.spy.start).toHaveBeenCalledTimes(1);
    expect(document.querySelectorAll("canvas")).toHaveLength(1);
    expect(document.getElementById("c")).toBe(canvas);
    expect(document.querySelectorAll("#tip, #panel")).toHaveLength(2);
    expect(document.querySelector("#nav .views")).not.toBeNull();

    act(() => held.store.set({ stats: "3 tasks" }));
    expect(document.querySelector("#nav .sub")!.textContent).toContain("3 tasks");

    act(() => root.unmount());
    expect(made.spy.stop).not.toHaveBeenCalled();
    root = createRoot(document.getElementById("root")!);
  });
});
