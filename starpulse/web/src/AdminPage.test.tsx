// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";
import { AdminStore } from "./features/admin/adminPrefs";
import { HistoryWindowStore } from "./features/admin/historyWindow";
import { applyTheme } from "./features/admin/theme/apply";
import { BUILTIN, SLATE, build } from "./features/admin/theme/scheme";
import { THEME_KEY, ThemeStore } from "./features/admin/theme/themeStore";

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
    await act(async () => root.render(<AdminPage store={new AdminStore()} theme={new ThemeStore()} window={new HistoryWindowStore()} hint={null} />));

    const card = [...host.querySelectorAll("#admin .card")].find((c) => c.querySelector("h2")?.textContent?.startsWith("Tracker"));
    expect(card?.textContent).toContain("Connect a tracker");
  });

  it("draws an Autopilot card holding the switch and scheduler's quiet hours, on and in the window's zone, and the Server card holds neither", async () => {
    const status = { enabled: true, harness: "claude", quietHours: { start: "22:00", end: "07:00", timezone: "America/Phoenix" }, sampledAt: null, dimensions: [] };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/api/scheduler") ? new Response(JSON.stringify(status)) : new Response("{}", { status: 503 }))));

    await act(async () => root.render(<AdminPage store={new AdminStore()} theme={new ThemeStore()} window={new HistoryWindowStore()} hint={null} />));
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

  const theme = () => new ThemeStore(applyTheme, localStorage);
  const mountAdmin = async (t: ThemeStore) => act(async () => root.render(<AdminPage store={new AdminStore()} theme={t} window={new HistoryWindowStore()} hint={null} />));
  const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>("#admin .thm .pick")].find((b) => b.querySelector(".nm")?.textContent === name)!;
  const rootToken = (k: string) => document.documentElement.style.getPropertyValue(`--${k}`);

  it("lays out two columns: This browser then the server cards, and Preview with Theme directly under it", async () => {
    await mountAdmin(theme());

    const cols = [...host.querySelectorAll("#admin .grid > .col")];
    const heads = (c: Element) => [...c.querySelectorAll(":scope .card > h2, :scope > div > .card > h2")].map((h) => h.textContent?.split(/\s/)[0]);
    expect(cols).toHaveLength(2);
    expect(heads(cols[0])[0]).toBe("This");
    expect(heads(cols[0])).toEqual(expect.arrayContaining(["Server", "Autopilot", "Tracker"]));
    expect(heads(cols[1])).toEqual(["Preview", "Theme"]);
  });

  it("lists the nine packs and the Slate background, with StarPulse on Slate marked on a fresh browser", async () => {
    await mountAdmin(theme());

    expect([...host.querySelectorAll("#admin .thm .packs .pick")]).toHaveLength(Object.keys(BUILTIN).length);
    expect(tile("StarPulse").getAttribute("aria-pressed")).toBe("true");
    expect(tile("Slate").getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
    expect(rootToken("ok")).toBe(build(BUILTIN.starpulse, SLATE).t.ok);
  });

  it("applies a clicked pack at once, saves it, and a reload keeps it", async () => {
    await mountAdmin(theme());

    await act(async () => tile("Nord").click());

    const want = build(BUILTIN.nord, SLATE).t;
    expect(JSON.parse(localStorage.getItem(THEME_KEY)!).pack).toBe("nord");
    expect(rootToken("ok")).toBe(want.ok);
    expect(tile("Nord").getAttribute("aria-pressed")).toBe("true");
    expect(tile("StarPulse").getAttribute("aria-pressed")).toBe("false");

    act(() => root.unmount());
    root = createRoot(host);
    const reloaded = theme();
    await mountAdmin(reloaded);
    expect(reloaded.get().pack).toBe("nord");
    expect(tile("Nord").getAttribute("aria-pressed")).toBe("true");
  });
});
