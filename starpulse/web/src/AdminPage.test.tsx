// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";
import { AdminStore } from "./features/admin/adminPrefs";
import { HistoryWindowStore } from "./features/admin/historyWindow";
import { ForwardingStore } from "./features/forwarding/forwarding";

let host: HTMLDivElement, root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: "offline" }), { status: 503 })));
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the Admin view", () => {
  it("hosts Connect a tracker, which left the Kanban's filters row", async () => {
    await act(async () => root.render(<AdminPage store={new AdminStore()} window={new HistoryWindowStore()} forwarding={new ForwardingStore()} hint={null} />));

    const card = [...host.querySelectorAll("#admin .card")].find((c) => c.querySelector("h2")?.textContent?.startsWith("Tracker"));
    expect(card?.textContent).toContain("Connect a tracker");
  });
});
