import { describe, expect, it, vi } from "vitest";
import { QuietHoursStore, type Window } from "./quietHours";

const NIGHT: Window = { start: "22:00", end: "07:00", timezone: "America/Phoenix" };

/** A server that keeps the window as `PUT /api/autopilot` does: a window or null, with an unreadable one refused. */
function server(opts: { window?: Window | null; status?: number } = {}) {
  let window = opts.window ?? null;
  const sent: unknown[] = [];
  const fetcher = vi.fn<typeof fetch>((_url, init) => {
    if (opts.status) return Promise.resolve(new Response(JSON.stringify({ error: "this instance runs no autopilot" }), { status: opts.status }));
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as { quietHours: Window | null };
      sent.push(body);
      if (body.quietHours && body.quietHours.start === body.quietHours.end) {
        return Promise.resolve(new Response(JSON.stringify({ error: "quiet hours start and end must differ" }), { status: 400 }));
      }
      window = body.quietHours;
    }
    return Promise.resolve(new Response(JSON.stringify({ enabled: true, quietHours: window, sampledAt: null, dimensions: [] })));
  });
  return { fetcher, sent };
}

describe("the Server card's autopilot quiet hours", () => {
  it("reads the window the server keeps, and the controls start on it", async () => {
    const store = new QuietHoursStore(server({ window: NIGHT }).fetcher, () => "UTC");

    await store.load();

    expect(store.get()).toMatchObject({ current: NIGHT, loaded: true, draft: { on: true, start: "22:00", end: "07:00" } });
    expect(store.zone()).toBe("America/Phoenix"); // the window's own zone, not the browser's
    expect(store.dirty()).toBe(false);
  });

  it("with no window offers one off, in the browser's zone", async () => {
    const store = new QuietHoursStore(server().fetcher, () => "America/Phoenix");

    await store.load();

    expect(store.get()).toMatchObject({ current: null, loaded: true, draft: { on: false } });
    expect(store.zone()).toBe("America/Phoenix");
  });

  it("names why it cannot be read, as on a server with no autopilot", async () => {
    const store = new QuietHoursStore(server({ status: 404 }).fetcher, () => "UTC");

    await store.load();

    expect(store.get()).toMatchObject({ loaded: false, unavailable: "this instance runs no autopilot" });
  });

  it("saves a window turned on in the browser's zone, and the server's answer becomes the window", async () => {
    const { fetcher, sent } = server();
    const store = new QuietHoursStore(fetcher, () => "America/Phoenix", () => 1000);
    await store.load();

    store.edit({ on: true, start: "21:30" });
    expect(store.dirty()).toBe(true);
    await store.save();

    expect(sent).toEqual([{ quietHours: { start: "21:30", end: "07:00", timezone: "America/Phoenix" } }]);
    expect(store.get()).toMatchObject({ current: { start: "21:30", end: "07:00" }, phase: { kind: "saved", at: 1000 } });
    expect(store.dirty()).toBe(false);
  });

  it("clears the window when turned off", async () => {
    const { fetcher, sent } = server({ window: NIGHT });
    const store = new QuietHoursStore(fetcher, () => "UTC");
    await store.load();

    store.edit({ on: false });
    await store.save();

    expect(sent).toEqual([{ quietHours: null }]);
    expect(store.get().current).toBeNull();
  });

  it("shows the server's refusal and keeps the window it had", async () => {
    const store = new QuietHoursStore(server({ window: NIGHT }).fetcher, () => "UTC");
    await store.load();

    store.edit({ end: "22:00" });
    await store.save();

    expect(store.get()).toMatchObject({ current: NIGHT, phase: { kind: "refused", reason: "quiet hours start and end must differ" } });
    store.edit({ end: "06:00" });
    expect(store.get().phase).toEqual({ kind: "idle" }); // editing clears the last message
  });
});
