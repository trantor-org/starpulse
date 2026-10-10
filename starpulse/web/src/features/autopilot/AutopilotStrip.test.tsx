// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AutopilotStrip } from "./AutopilotStrip";
import { AutopilotStore } from "./autopilot";

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

let host: HTMLDivElement, root: Root, enabled: boolean, status: () => unknown, fetcher: ReturnType<typeof vi.fn<typeof fetch>>;
const reply = (body: unknown, code = 200) => Promise.resolve(new Response(JSON.stringify(body), { status: code }));
const settle = () => act(async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); });
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel);
const open = vi.fn();

async function draw(body: Record<string, unknown> = {}, opts: { put?: () => Promise<Response>; down?: boolean } = {}) {
  enabled = (body.enabled as boolean | undefined) ?? true;
  status = () => ({ sampledAt: NOW, dimensions: dims(), inFlight: SESSIONS, next: NEXT, ...body, enabled });
  fetcher = vi.fn<typeof fetch>((_url, init) => {
    if (opts.down) return reply({ error: "This server has no autopilot." }, 404);
    if (init?.method === "PUT") {
      if (opts.put) return opts.put();
      enabled = (JSON.parse(String(init.body)) as { enabled: boolean }).enabled;
    }
    return reply(status());
  });
  const store = new AutopilotStore(fetcher);
  await act(async () => root.render(<AutopilotStrip store={store} now={NOW} openTask={open} />));
  await settle();
  return store;
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  open.mockClear();
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe("the autopilot strip", () => {
  it("draws the switch on and a labelled meter per dimension with its use against its limit", async () => {
    await draw();

    expect(q('[role="switch"]')?.getAttribute("aria-checked")).toBe("true");
    const meters = [...host.querySelectorAll(".dm")].map((m) => m.querySelector(".r")?.textContent);
    expect(meters).toEqual(["CPU41/80%", "RAM58/85%", "Sessions2/4", "Review13/24 pts"]);
    expect(host.querySelector(".ap.off")).toBeNull();
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

  it("names the next pick by its task and opens that task's modal on a click", async () => {
    await draw();

    const next = q("button.nx")!;
    expect(next.textContent).toBe("Next TASK-21");
    expect(next.className).toContain("starting");
    act(() => next.click());

    expect(open).toHaveBeenCalledWith("TASK-21");
  });

  it("says a pick that waits, and which dimension it waits on, in its label for screen readers", async () => {
    await draw({ next: { task: "TASK-21", title: "Next up", verdict: "waits", reason: "RAM 91/85%" } });

    const next = q("button.nx")!;
    expect(next.className).toContain("waits");
    expect(next.getAttribute("aria-label")).toBe("Next TASK-21, waits: RAM 91/85%");
  });

  it("says nothing is eligible when the server names no pick, and draws no pick when the server does not serve one", async () => {
    await draw({ next: null });

    expect(q(".nx.none")?.textContent).toBe("Next · nothing eligible");
    expect(q("button.nx")).toBeNull();
  });

  it("opens the sessions in flight from the Sessions meter and closes on Escape", async () => {
    await draw();

    expect(q('[role="menu"]')).toBeNull();
    act(() => q<HTMLButtonElement>(".dmb")!.click());

    const rows = [...host.querySelectorAll('[role="menuitem"]')];
    expect(rows.map((r) => r.querySelector(".id")?.textContent)).toEqual(["TASK-11", "TASK-12"]);
    expect(rows[0].getAttribute("href")).toBe("#demo-session-0011");
    expect(rows[0].textContent).toContain("opus · high");

    act(() => void document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));

    expect(q('[role="menu"]')).toBeNull();
  });

  it("says no session is running when the list is empty, and that the server does not list them when it serves none", async () => {
    await draw({ dimensions: dims({ sessions: 0 }), inFlight: [] });
    act(() => q<HTMLButtonElement>(".dmb")!.click());
    expect(q(".ap-ses .none")?.textContent).toBe("No autopilot session is running.");

    act(() => root.unmount());
    root = createRoot(host);
    await draw({ inFlight: undefined });
    act(() => q<HTMLButtonElement>(".dmb")!.click());
    expect(q(".ap-ses .none")?.textContent).toContain("does not list");
  });

  it("reads paused with the count of sessions still running, dims the meters and names no pick", async () => {
    await draw({ enabled: false, dimensions: dims({ sessions: 3 }) });

    expect(q('[role="switch"]')?.getAttribute("aria-checked")).toBe("false");
    expect(q(".ap.off")).not.toBeNull();
    expect(q(".paused")?.textContent).toBe("Paused · 3 running");
    expect(q(".nx")).toBeNull();
  });

  it("turns admission off with one click and no dialog, and on again", async () => {
    await draw();

    await act(async () => q<HTMLButtonElement>('[role="switch"]')!.click());
    await settle();

    expect(fetcher).toHaveBeenLastCalledWith("/api/autopilot", { method: "PUT", body: JSON.stringify({ enabled: false }) });
    expect(q('[role="switch"]')?.getAttribute("aria-checked")).toBe("false");
    expect(document.querySelector('[role="dialog"], [role="alertdialog"]')).toBeNull();

    await act(async () => q<HTMLButtonElement>('[role="switch"]')!.click());
    await settle();

    expect(q('[role="switch"]')?.getAttribute("aria-checked")).toBe("true");
  });

  it("alerts why a switch change was refused, leaves the switch where it was, and dismisses", async () => {
    await draw({}, { put: () => reply({ error: "Autopilot changes are taken only from loopback or a private address" }, 403) });

    await act(async () => q<HTMLButtonElement>('[role="switch"]')!.click());
    await settle();

    expect(q('[role="alert"]')?.textContent).toContain("Autopilot changes are taken only from loopback or a private address");
    expect(q('[role="switch"]')?.getAttribute("aria-checked")).toBe("true");

    act(() => q<HTMLButtonElement>('[role="alert"] .dismiss')!.click());

    expect(q('[role="alert"]')).toBeNull();
  });

  it("says autopilot is unavailable when the server has none, with the server's reason on hover", async () => {
    await draw({}, { down: true });

    const chip = q(".ap.down")!;
    expect(chip.textContent).toBe("Autopilot unavailable");
    expect(chip.getAttribute("title")).toBe("This server has no autopilot.");
    expect(q('[role="switch"]')).toBeNull();
  });

  it("reads again on an interval while its view shows, and stops when it unmounts", async () => {
    vi.useFakeTimers();
    await draw();
    const reads = () => fetcher.mock.calls.filter(([, init]) => !init?.method).length;
    expect(reads()).toBe(1);

    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(reads()).toBe(2);

    act(() => root.unmount());
    root = createRoot(host);
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(reads()).toBe(2);
  });
});
