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

  it("draws an Autopilot card holding the switch and autopilot's quiet hours, on and in the window's zone, and the Server card holds neither", async () => {
    const status = { enabled: true, quietHours: { start: "22:00", end: "07:00", timezone: "America/Phoenix" }, sampledAt: null, dimensions: [] };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/api/autopilot") ? new Response(JSON.stringify(status)) : new Response("{}", { status: 503 }))));

    await act(async () => root.render(<AdminPage store={new AdminStore()} window={new HistoryWindowStore()} forwarding={new ForwardingStore()} hint={null} />));
    await act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });

    const cards = [...host.querySelectorAll("#admin .card")];
    const named = (name: string) => cards.find((c) => c.querySelector("h2")?.textContent?.startsWith(name));
    expect(named("Autopilot")?.querySelector('[role="switch"][aria-label="Autopilot"]')).not.toBeNull();
    expect(named("Autopilot")?.querySelector('[aria-label="Autopilot quiet hours"]')).not.toBeNull();
    expect(named("Server")?.textContent).not.toContain("quiet hours");
    const sw = host.querySelector<HTMLButtonElement>('[aria-label="Autopilot quiet hours"]');
    expect(sw?.getAttribute("aria-checked")).toBe("true");
    expect(host.querySelector<HTMLInputElement>('[aria-label="Quiet hours start"]')?.value).toBe("22:00");
    expect(host.querySelector<HTMLInputElement>('[aria-label="Quiet hours end"]')?.value).toBe("07:00");
    expect(host.textContent).toContain("Times in America/Phoenix");
  });
});
