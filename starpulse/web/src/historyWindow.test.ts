import { describe, expect, it, vi } from "vitest";
import { ROUTES } from "./demo";
import { HistoryWindowStore, type WindowState } from "./historyWindow";

const DECLARED: WindowState = { hours: 6, default: 6, overridden: false };
const REFUSAL = "history window must be between 1 and 72 hours; got 200";

/** A server that keeps one window as the endpoint does: PUT sets it, DELETE returns the default, anything outside 1-72 is refused. */
function server(opts: { down?: boolean } = {}) {
  let state = { ...DECLARED };
  const fetcher = vi.fn<typeof fetch>((_url, init) => {
    if (opts.down) return Promise.reject(new Error("offline"));
    const method = init?.method ?? "GET";
    if (method === "PUT") {
      const { hours } = JSON.parse(String(init?.body)) as { hours: unknown };
      if (typeof hours !== "number" || hours < 1 || hours > 72) {
        return Promise.resolve(new Response(JSON.stringify({ error: `history window must be between 1 and 72 hours; got ${hours}` }), { status: 400 }));
      }
      state = { hours, default: 6, overridden: true };
    }
    if (method === "DELETE") state = { ...DECLARED };
    return Promise.resolve(new Response(JSON.stringify(state)));
  });
  return fetcher;
}

describe("the Server card's history window", () => {
  it("reads the window and its declared default, and the input starts on the window", async () => {
    const store = new HistoryWindowStore(server());

    await store.load();

    expect(store.get().current).toEqual(DECLARED);
    expect(store.get().draft).toBe("6");
    expect(store.dirty()).toBe(false);
  });

  it("names why the window cannot be read, and leaves the controls without a window", async () => {
    const refused = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: "not on the LAN" }), { status: 403 })));
    const down = new HistoryWindowStore(server({ down: true }));
    const forbidden = new HistoryWindowStore(refused);

    await down.load();
    await forbidden.load();

    expect(down.get()).toMatchObject({ current: null, unavailable: "the server did not answer" });
    expect(forbidden.get()).toMatchObject({ current: null, unavailable: "not on the LAN" });
  });

  it("is dirty once the input differs from the window, and editing clears the last message", async () => {
    const store = new HistoryWindowStore(server());
    await store.load();
    store.edit("200");
    await store.save();
    expect(store.get().phase.kind).toBe("refused");

    store.edit("24");

    expect(store.get().phase).toEqual({ kind: "idle" });
    expect(store.dirty()).toBe(true);
    store.edit(" 6 ");
    expect(store.dirty()).toBe(false);
  });

  it("saves a valid window with a PUT, shows the server's answer and when it was saved", async () => {
    const fetcher = server();
    const store = new HistoryWindowStore(fetcher, () => 1700);
    await store.load();
    store.edit("24");

    await store.save();

    expect(fetcher).toHaveBeenLastCalledWith("/api/history-window", { method: "PUT", body: JSON.stringify({ hours: 24 }) });
    expect(store.get().current).toEqual({ hours: 24, default: 6, overridden: true });
    expect(store.get().draft).toBe("24");
    expect(store.get().phase).toEqual({ kind: "saved", at: 1700 });
    expect(store.dirty()).toBe(false);
  });

  it("shows the server's refusal of 200, keeps the window and the typed value", async () => {
    const store = new HistoryWindowStore(server());
    await store.load();
    store.edit("200");

    await store.save();

    expect(store.get().phase).toEqual({ kind: "refused", reason: REFUSAL });
    expect(store.get().current).toEqual(DECLARED);
    expect(store.get().draft).toBe("200");
  });

  it("sends text that is not a number as typed, so the server names it", async () => {
    const fetcher = server();
    const store = new HistoryWindowStore(fetcher);
    await store.load();

    for (const text of ["abc", ""]) {
      store.edit(text);
      await store.save();
      expect(fetcher).toHaveBeenLastCalledWith("/api/history-window", { method: "PUT", body: JSON.stringify({ hours: text }) });
      expect(store.get().phase).toEqual({ kind: "refused", reason: `history window must be between 1 and 72 hours; got ${text}` });
    }
  });

  it("reads an unreachable server and an unreadable answer as a refusal with that reason", async () => {
    const lost = new HistoryWindowStore(vi.fn<typeof fetch>(() => Promise.reject(new Error("offline"))));
    const garbled = new HistoryWindowStore(vi.fn<typeof fetch>(() => Promise.resolve(new Response("<html>", { status: 502 }))));
    lost.edit("24");
    garbled.edit("24");

    await lost.save();
    await garbled.save();

    expect(lost.get().phase).toEqual({ kind: "refused", reason: "the change did not reach the server" });
    expect(garbled.get().phase).toEqual({ kind: "refused", reason: "the server answered 502" });
  });

  it("resets with a DELETE: the window returns to the declared default and the input follows", async () => {
    const fetcher = server();
    const store = new HistoryWindowStore(fetcher, () => 1800);
    await store.load();
    store.edit("24");
    await store.save();

    await store.reset();

    expect(fetcher).toHaveBeenLastCalledWith("/api/history-window", { method: "DELETE" });
    expect(store.get().current).toEqual(DECLARED);
    expect(store.get().draft).toBe("6");
    expect(store.get().phase).toEqual({ kind: "saved", at: 1800 });
  });

  it("shows a refused reset and keeps the override", async () => {
    const store = new HistoryWindowStore(server());
    await store.load();
    store.edit("24");
    await store.save();
    const refusing = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: "not on the LAN" }), { status: 403 })));
    const kept = store.get().current;
    const failing = new HistoryWindowStore(refusing);

    await failing.reset();

    expect(failing.get().phase).toEqual({ kind: "refused", reason: "not on the LAN" });
    expect(store.get().current).toEqual(kept);
  });

  it("sends one save at a time", async () => {
    const fetcher = server();
    const store = new HistoryWindowStore(fetcher);
    await store.load();
    store.edit("24");

    await Promise.all([store.save(), store.save()]);

    expect(fetcher.mock.calls.filter(([, init]) => init?.method === "PUT")).toHaveLength(1);
  });

  it("tells subscribers about each change and stops after they leave", async () => {
    const store = new HistoryWindowStore(server());
    const heard = vi.fn();
    const leave = store.subscribe(heard);

    await store.load();
    expect(heard).toHaveBeenCalled();
    heard.mockClear();
    leave();
    store.edit("24");

    expect(heard).not.toHaveBeenCalled();
  });

  it("is a route the public demo lists, with why it has no server window to read", async () => {
    const why = ROUTES["/api/history-window"];
    const demo = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: why }), { status: 404 })));
    const store = new HistoryWindowStore(demo);

    await store.load();

    expect(typeof why).toBe("string");
    expect(store.get().unavailable).toBe(why);
  });
});
