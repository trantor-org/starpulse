// @vitest-environment jsdom
// The server's "Opens on" arrives after the first frame: a bare address follows it unless the visitor already chose a view.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AdminStore } from "./features/admin/adminPrefs";
import { HudStore } from "./render/hud";
import { BOARD_DRAWN } from "./shared/boardDrawn";

const boot = vi.hoisted(() => ({ held: null as object | null }));
vi.mock("./boot", () => ({ booted: () => boot.held }));
vi.mock("./lazyViews", () => ({
  Kanban: () => <div id="kb" />,
  Dags: () => <div id="dg" />,
  AdminPage: () => <div id="admin" />,
  OrbitCard: () => <div id="og" />,
  prefetchViews: () => () => {},
}));

let host: HTMLDivElement, root: Root, admin: AdminStore;
const settle = () => act(async () => { for (let i = 0; i < 5; i++) await new Promise((resolve) => setTimeout(resolve, 0)); });
const mount = async (address: string) => {
  history.replaceState(null, "", address);
  const store = new HudStore();
  store.set({ tree: { states: ["ready"], subs: {}, children: {} }, states: [{ id: "ready", name: "Ready", count: 2 }] });
  admin = new AdminStore({ style: { setProperty: () => {} }, classList: { toggle: () => {} } }, vi.fn() as never);
  boot.held = { store, admin, canvas: document.createElement("canvas"), tip: document.createElement("div"), panel: document.createElement("div"), renderer: new Proxy({}, { get: () => () => {} }) };
  root = createRoot(host);
  performance.mark(BOARD_DRAWN);
  await act(async () => root.render(<App />));
  await settle();
};

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}")));
  host = document.body.appendChild(document.createElement("div"));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  performance.clearMarks(BOARD_DRAWN);
  vi.unstubAllGlobals();
});

describe("the view a bare address opens on", () => {
  it("moves to the Kanban when the server's Opens on names it", async () => {
    await mount("/");
    expect(host.querySelector("#kb")).toBeNull();

    await act(async () => admin.adopt({ display: { view: "kanban" } }));
    await settle();

    expect(host.querySelector("#kb")).not.toBeNull();
  });

  it("keeps the view an address names, whatever the server holds", async () => {
    await mount("/?view=constellation");

    await act(async () => admin.adopt({ display: { view: "kanban" } }));
    await settle();

    expect(host.querySelector("#kb")).toBeNull();
  });
});
