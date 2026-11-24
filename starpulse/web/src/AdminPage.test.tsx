// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AdminPage } from "./AdminPage";
import { AdminStore } from "./features/admin/adminPrefs";
import { HistoryWindowStore } from "./features/admin/historyWindow";
import { applyTheme } from "./features/admin/theme/apply";
import { BUILTIN, SLATE, build } from "./features/admin/theme/scheme";
import { ThemeStore } from "./features/admin/theme/themeStore";

let host: HTMLDivElement, root: Root;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
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
  it("draws an Autopilot card holding the switch and scheduler's quiet hours, on and in the window's zone, and the Server card holds neither", async () => {
    const status = { enabled: true, harness: "claude", quietHours: { start: "22:00", end: "07:00", timezone: "America/Phoenix" }, sampledAt: null, dimensions: [] };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/api/admin") ? new Response(JSON.stringify(status)) : new Response("{}", { status: 503 }))));

    await act(async () => root.render(<AdminPage store={new AdminStore()} theme={new ThemeStore()} window={new HistoryWindowStore()} />));
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

  const theme = () => new ThemeStore(applyTheme);
  /** A server that keeps each theme written to it and answers a read with the last one; `puts` holds every body written. */
  const serve = () => {
    const puts: { theme?: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: { method?: string; body?: string }) => {
      if (init?.method === "PUT") {
        puts.push(JSON.parse(init.body!));
        return new Response("{}");
      }
      return new Response(JSON.stringify({ theme: puts.at(-1)?.theme }));
    }));
    return puts;
  };
  const mountAdmin = async (t: ThemeStore) => act(async () => root.render(<AdminPage store={new AdminStore()} theme={t} window={new HistoryWindowStore()} />));
  const tile = (name: string) => [...host.querySelectorAll<HTMLButtonElement>("#admin .thm .pick")].find((b) => b.querySelector(".nm")?.textContent === name)!;
  const rootToken = (k: string) => document.documentElement.style.getPropertyValue(`--${k}`);

  it("lays out two columns: Display then the server cards, and Preview with Theme directly under it", async () => {
    await mountAdmin(theme());

    const cols = [...host.querySelectorAll("#admin .grid > .col")];
    const heads = (c: Element) => [...c.querySelectorAll(":scope .card > h2, :scope > div > .card > h2")].map((h) => h.textContent?.split(/\s/)[0]);
    expect(cols).toHaveLength(2);
    expect(heads(cols[0])[0]).toBe("Display");
    expect(heads(cols[0])).toEqual(expect.arrayContaining(["Server", "Autopilot"]));
    expect(heads(cols[1])).toEqual(["Preview", "Theme"]);
  });

  it("lists the nine packs and the Slate background, with StarPulse on Slate marked while the server holds none", async () => {
    const puts = serve();
    await mountAdmin(theme());

    expect([...host.querySelectorAll("#admin .thm .packs .pick")]).toHaveLength(Object.keys(BUILTIN).length);
    expect(tile("StarPulse").getAttribute("aria-pressed")).toBe("true");
    expect(tile("Slate").getAttribute("aria-pressed")).toBe("true");
    expect(puts).toEqual([]);
    expect(rootToken("ok")).toBe(build(BUILTIN.starpulse, SLATE).t.ok);
  });

  it("applies a clicked pack at once, saves it for every device, and a reload adopts it", async () => {
    const puts = serve();
    await mountAdmin(theme());

    await act(async () => tile("Nord").click());

    const want = build(BUILTIN.nord, SLATE).t;
    expect(puts.at(-1)?.theme).toMatchObject({ pack: "nord" });
    expect(host.textContent).toContain("Saved for every device");
    expect(rootToken("ok")).toBe(want.ok);
    expect(tile("Nord").getAttribute("aria-pressed")).toBe("true");
    expect(tile("StarPulse").getAttribute("aria-pressed")).toBe("false");

    act(() => root.unmount());
    root = createRoot(host);
    const reloaded = theme();
    await mountAdmin(reloaded);
    reloaded.adopt(await (await fetch("/api/admin")).json());
    await act(async () => {});
    expect(reloaded.get().pack).toBe("nord");
    expect(tile("Nord").getAttribute("aria-pressed")).toBe("true");
  });

  it("tells a refused write in the box with the server's reason and Not saved. as its own line", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: { method?: string }) => (init?.method === "PUT" ? new Response(JSON.stringify({ error: "theme.pack is unknown" }), { status: 400 }) : new Response("{}"))));
    await mountAdmin(theme());
    expect(host.querySelector("#admin .foot")?.textContent).toContain("Changes save for every device as you make them.");

    await act(async () => tile("Nord").click());

    expect(host.querySelector("#admin .thm .refusal")?.textContent).toBe("the server refused the changetheme.pack is unknown");
    expect(host.querySelector("#admin .thm .no")?.textContent).toBe("Not saved.");
  });
});
