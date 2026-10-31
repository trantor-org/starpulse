// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SchedulerCard } from "./SchedulerCard";
import { SchedulerStore, pushSchedulerStatus } from "./scheduler";
import { QuietHoursStore } from "../admin/quietHours";

const NOW = 10_000;
const dims = (over: Record<string, number> = {}) =>
  (["cpu", "memory", "sessions", "review"] as const).map((name) => ({
    name,
    use: over[name] ?? { cpu: 41, memory: 58, sessions: 2, review: 13 }[name],
    limit: { cpu: 80, memory: 85, sessions: 4, review: 24 }[name],
  }));
const SESSIONS = [
  { task: "TASK-11", title: "Wire the strip", model: "opus · high", started: NOW - 14 * 60, url: "#demo-session-0011" },
  { task: "TASK-12", title: "Move the tracker card", model: "sonnet · high", started: NOW - 37 * 60, url: "#demo-session-0012" },
];
const NEXT = { task: "TASK-21", title: "Next up", verdict: "starting", reason: "" };
const HARNESSES = {
  tiers: ["fast", "standard"],
  harnesses: [
    { name: "claude", label: "Claude Code", sessions: true, reason: "", tiers: {} },
    { name: "cursor", label: "Cursor", sessions: true, reason: "", tiers: {} },
  ],
};
const BY_HARNESS = { claude: { use: 2, limit: 3 }, cursor: { use: 0, limit: 2 } };

let host: HTMLDivElement, root: Root, enabled: boolean, harness: string, cap: number | null, status: () => unknown, fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
const reply = (body: unknown, code = 200) => Promise.resolve(new Response(JSON.stringify(body), { status: code }));
const settle = () => act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel);
const SWITCH = '[role="switch"][aria-label="Autopilot"]';
const HARNESS = '[role="radiogroup"][aria-label="Harness"]';

async function draw(body: Record<string, unknown> = {}, opts: { put?: () => Promise<Response>; down?: boolean; cap?: number } = {}) {
  cap = opts.cap ?? null;
  enabled = (body.enabled as boolean | undefined) ?? true;
  harness = (body.harness as string | undefined) ?? "claude";
  status = () => ({
    sampledAt: NOW, dimensions: dims(), inFlight: SESSIONS, next: NEXT, quietHours: null,
    sessionsByHarness: BY_HARNESS, pauses: [], ...body, enabled, harness,
    sessionCap: { harness, limit: cap ?? 4, source: cap === null ? "starpulse.toml" : "admin", configLimit: 4 },
  });
  fetcher = vi.fn<typeof fetch>((url, init) => {
    if (String(url).endsWith("/api/harnesses")) return reply(HARNESSES);
    if (opts.down) return reply({ error: "This server has no scheduler." }, 404);
    if (init?.method === "PUT") {
      if (opts.put) return opts.put();
      const sent = JSON.parse(String(init.body)) as { enabled?: boolean; harness?: string; sessionCap?: number | null };
      if ("sessionCap" in sent) cap = sent.sessionCap ?? null;
      if (typeof sent.enabled === "boolean") enabled = sent.enabled;
      if (typeof sent.harness === "string") harness = sent.harness;
    }
    return reply(status());
  });
  const store = new SchedulerStore(fetcher);
  const quiet = new QuietHoursStore(fetcher, () => "America/Phoenix");
  await act(async () => root.render(<SchedulerCard store={store} quiet={quiet} clock="24" />));
  await settle();
  return store;
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe("the Admin view's Autopilot card", () => {
  it("draws the switch on and a labelled meter per dimension with its use against its limit", async () => {
    await draw();

    expect(q("h2")?.textContent).toContain("Autopilot");
    expect(q(SWITCH)?.getAttribute("aria-checked")).toBe("true");
    expect(q(".state")?.textContent).toBe("On");
    const meters = [...host.querySelectorAll(".dm")].map((m) => m.querySelector(".r")?.textContent);
    expect(meters).toEqual(["CPU41/80%", "RAM58/85%", "Sessions2/4", "Review13/24 pts"]);
    expect(q(".ap.off")).toBeNull();
  });

  it("offers harness Segments beside On/Paused and selects another with a PUT", async () => {
    await draw();

    const radios = [...host.querySelectorAll(`${HARNESS} [role="radio"]`)] as HTMLButtonElement[];
    expect(radios.map((b) => [b.textContent, b.getAttribute("aria-pressed"), b.disabled])).toEqual([
      ["Claude Code", "true", false],
      ["Cursor", "false", false],
    ]);
    expect(q(".hint")?.textContent).toContain("Starts on the picked harness");

    await act(async () => radios[1].click());
    await settle();

    expect(fetcher).toHaveBeenCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ harness: "cursor" }) });
    expect(radios[1].getAttribute("aria-pressed")).toBe("true");
  });

  it("disables an exhausted harness and scopes the Sessions meter hint to the selection", async () => {
    await draw({
      pauses: [{ harness: "claude", until: 75_600, reason: "usage limit" }],
      harness: "cursor",
      dimensions: dims({ sessions: 0 }),
      sessionsByHarness: { claude: { use: 1, limit: 3 }, cursor: { use: 0, limit: 2 } },
    });

    const claude = host.querySelector(`${HARNESS} [role="radio"]`) as HTMLButtonElement;
    expect(claude.disabled).toBe(true);
    expect(claude.title).toContain("credits until");
    expect(host.textContent).toContain("Cursor's session cap");
    expect(host.textContent).toMatch(/Claude Code 1\/3 running/);
    expect(q(".inflight")?.closest(".row")?.querySelector(".hint")?.textContent).toContain("on Cursor");
  });

  it("prints a fractional use as a whole number, and still fills its bar to the fraction", async () => {
    await draw({ dimensions: dims({ cpu: 76.07209997714222, memory: 37.84587044556782 }) });

    const meters = [...host.querySelectorAll(".dm")].map((m) => m.querySelector(".r")?.textContent);
    expect(meters.slice(0, 2)).toEqual(["CPU76/80%", "RAM38/85%"]);
    expect(parseFloat(q<HTMLElement>(".dm .m i")!.style.width)).toBeCloseTo(95.09, 2);
  });

  it("turns a meter amber from 80% of its limit and red past it", async () => {
    await draw({ dimensions: dims({ cpu: 66, memory: 91 }) });

    const level = (i: number) => host.querySelectorAll(".dm")[i].className;
    expect(level(0)).toContain("near");
    expect(level(1)).toContain("over");
    expect(level(2)).not.toMatch(/near|over/);
  });

  it("names the next pick as text: its task, title and that it starts, with nothing to click", async () => {
    await draw();

    const next = q(".nx")!;
    expect(next.className).toContain("starting");
    expect(next.textContent).toBe("TASK-21Next upstarting");
    expect(next.querySelector("button, a")).toBeNull();
  });

  it("says a pick that waits, and what it waits on", async () => {
    await draw({ next: { task: "TASK-21", title: "Next up", verdict: "waits", reason: "quiet hours" } });

    expect(q(".nx")?.className).toContain("waits");
    expect(q(".nx .why")?.textContent).toBe("waits: quiet hours");
  });

  it("says nothing is eligible when the server names no pick", async () => {
    await draw({ next: null });

    expect(q(".nx.none")?.textContent).toBe("Nothing eligible");
  });

  it("counts the sessions in flight from the Sessions dimension, with no list of them", async () => {
    await draw();

    expect(q(".inflight")?.textContent).toBe("2 running");
    expect(host.querySelector(".ap-ses, .inflight a")).toBeNull();
  });

  it("counts the listed sessions when the server serves no Sessions dimension", async () => {
    await draw({ dimensions: dims().filter((d) => d.name !== "sessions") });

    expect(q(".inflight")?.textContent).toBe("2 running");
  });

  it("reads paused with the count of sessions still running, dims the meters and starts nothing", async () => {
    await draw({ enabled: false, dimensions: dims({ sessions: 3 }) });

    expect(q(SWITCH)?.getAttribute("aria-checked")).toBe("false");
    expect(q(".ap.off")).not.toBeNull();
    expect(q(".state")?.textContent).toBe("Paused");
    expect(q(".inflight")?.textContent).toBe("3 running");
    expect(q(".nx")?.textContent).toBe("Paused: nothing starts");
  });

  it("turns admission off with one click and no dialog, and on again", async () => {
    await draw();

    await act(async () => q<HTMLButtonElement>(SWITCH)!.click());
    await settle();

    expect(fetcher).toHaveBeenLastCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ enabled: false }) });
    expect(q(SWITCH)?.getAttribute("aria-checked")).toBe("false");
    expect(document.querySelector('[role="dialog"], [role="alertdialog"]')).toBeNull();

    await act(async () => q<HTMLButtonElement>(SWITCH)!.click());
    await settle();

    expect(q(SWITCH)?.getAttribute("aria-checked")).toBe("true");
  });

  it("alerts why a switch change was refused, leaves the switch where it was, and dismisses", async () => {
    await draw({}, { put: () => reply({ error: "Autopilot changes are taken only from loopback or a private address" }, 403) });

    await act(async () => q<HTMLButtonElement>(SWITCH)!.click());
    await settle();

    expect(q('[role="alert"]')?.textContent).toContain("Autopilot changes are taken only from loopback or a private address");
    expect(q(SWITCH)?.getAttribute("aria-checked")).toBe("true");

    act(() => q<HTMLButtonElement>('[role="alert"] .dismiss')!.click());

    expect(q('[role="alert"]')).toBeNull();
  });

  it("holds the quiet-hours row", async () => {
    await draw({ quietHours: { start: "22:00", end: "07:00", timezone: "America/Phoenix" } });

    expect(q('[role="switch"][aria-label="Autopilot quiet hours"]')?.getAttribute("aria-checked")).toBe("true");
    expect(q<HTMLInputElement>('[aria-label="Quiet hours start"]')?.value).toBe("22:00");
  });

  it("says scheduler cannot be read when the server has none, with the server's reason, and offers no controls", async () => {
    await draw({}, { down: true });

    expect(q(".refusal")?.textContent).toContain("This server has no scheduler.");
    expect(host.querySelector('[role="switch"]')).toBeNull();
  });

  it("reads once when the view opens, adds no GET on a timer, and takes a stream status without fetching", async () => {
    vi.useFakeTimers();
    await draw();
    const reads = () => fetcher.mock.calls.filter(([, init]) => !init?.method).length;
    const first = reads(); // the status, and the quiet-hours row's own read

    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(reads()).toBe(first);

    await act(async () => {
      pushSchedulerStatus({ sampledAt: NOW, dimensions: dims({ cpu: 10 }), inFlight: SESSIONS, next: null, enabled: true });
    });
    expect(reads()).toBe(first);
    expect(q(".nx.none")?.textContent).toBe("Nothing eligible");
  });

  describe("session cap", () => {
    const row = () => q('[aria-label="Session cap"]')!.closest(".row")!;
    const input = () => q<HTMLInputElement>('input[aria-label="Session cap"]')!;
    const button = (name: string) => [...row().querySelectorAll("button")].find((b) => b.textContent === name) as HTMLButtonElement | undefined;
    const type = (value: string) =>
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input(), value);
        input().dispatchEvent(new Event("input", { bubbles: true }));
      });

    it("shows the effective cap and says starpulse.toml sets it until an operator overrides it", async () => {
      await draw();

      expect(input().value).toBe("4");
      expect(row().textContent).toContain("starpulse.toml");
      expect(row().textContent).not.toContain("Admin override");
      expect(button("Use starpulse.toml")).toBeUndefined();
      expect(button("Save")!.disabled).toBe(true);
    });

    it("saves a whole number above zero as the cap and then says Admin overrides the config", async () => {
      await draw();

      await type("6");
      await act(async () => button("Save")!.click());
      await settle();

      expect(fetcher).toHaveBeenCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ sessionCap: 6 }) });
      expect(input().value).toBe("6");
      expect(row().textContent).toContain("Admin override");
      expect(row().textContent).toContain("starpulse.toml sets 4");
    });

    it("clears the override with a PUT of null and falls back to the configured cap", async () => {
      await draw({}, { cap: 9 });
      expect(input().value).toBe("9");

      await act(async () => button("Use starpulse.toml")!.click());
      await settle();

      expect(fetcher).toHaveBeenCalledWith("/api/scheduler", { method: "PUT", body: JSON.stringify({ sessionCap: null }) });
      expect(input().value).toBe("4");
      expect(row().textContent).not.toContain("Admin override");
    });

    it.each(["0", "-2", "2.5", ""])("offers no Save for %j, which is not a whole number above zero", async (value) => {
      await draw();

      await type(value);

      expect(button("Save")!.disabled).toBe(true);
    });

    it("names the server's reason when it refuses the cap", async () => {
      await draw({}, { put: () => reply({ error: "session cap must be a whole number above zero; got 6" }, 400) });

      await type("6");
      await act(async () => button("Save")!.click());
      await settle();

      expect(q(".refusal")?.textContent).toContain("session cap must be a whole number above zero");
    });
  });
});
