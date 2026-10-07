import { describe, expect, it, vi } from "vitest";
import { ROUTES } from "./demo";
import { ForwardingStore, type ForwardStatus } from "./forwarding";

const STATUS: ForwardStatus = {
  configured: true, url: "https://hub.example.test/api/forward", optIn: false, names: false, refused: false, lastSent: 100, problem: null,
  next: [{ stream: "machine:events", fields: { machine: "board", event: "MOVED", task: "TASK-1", time: 90 }, kept: ["session"] }],
  more: false,
  contract: { "machine:events": [{ field: "task", person: false }, { field: "actor", person: true }] },
};

/** A server that keeps one opt-in as the route does: PUT sets it and the answer follows it; anything but a boolean is refused. */
function server(opts: { down?: boolean; configured?: boolean } = {}) {
  let optIn = false;
  return vi.fn<typeof fetch>((_url, init) => {
    if (opts.down) return Promise.reject(new Error("offline"));
    if (opts.configured === false) return Promise.resolve(new Response(JSON.stringify({ configured: false })));
    if (init?.method === "PUT") {
      const body = JSON.parse(String(init.body)) as { opt_in: unknown };
      if (typeof body.opt_in !== "boolean") return Promise.resolve(new Response(JSON.stringify({ error: "forwarding takes a boolean" }), { status: 400 }));
      optIn = body.opt_in;
    }
    return Promise.resolve(new Response(JSON.stringify({ ...STATUS, optIn, names: optIn })));
  });
}

describe("the Forwarding card's store", () => {
  it("reads what the forwarder would send", async () => {
    const store = new ForwardingStore(server());

    await store.load();

    expect(store.get().current).toMatchObject({ configured: true, optIn: false, url: STATUS.url });
    expect(store.get().unavailable).toBe("");
  });

  it("reads an instance with no [forward] block as not configured", async () => {
    const store = new ForwardingStore(server({ configured: false }));

    await store.load();

    expect(store.get().current).toEqual({ configured: false });
  });

  it("names why the status cannot be read, and keeps the last status it had", async () => {
    const store = new ForwardingStore(server());
    await store.load();
    const down = vi.fn<typeof fetch>(() => Promise.reject(new Error("offline")));
    const failing = new ForwardingStore(down);
    const refused = new ForwardingStore(vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: "not on the LAN" }), { status: 403 }))));

    await failing.load();
    await refused.load();

    expect(failing.get()).toMatchObject({ current: null, unavailable: "the server did not answer" });
    expect(refused.get()).toMatchObject({ current: null, unavailable: "not on the LAN" });
    expect(store.get().current).not.toBeNull();
  });

  it("opts in by PUTting a boolean and shows the answer with the time it was saved", async () => {
    const fetcher = server();
    const store = new ForwardingStore(fetcher, () => 500);
    await store.load();

    await store.setOptIn(true);

    expect(fetcher).toHaveBeenLastCalledWith("/api/forwarding", { method: "PUT", body: JSON.stringify({ opt_in: true }) });
    expect(store.get().current).toMatchObject({ optIn: true, names: true });
    expect(store.get().phase).toEqual({ kind: "saved", at: 500 });
  });

  it("opts out the same way", async () => {
    const store = new ForwardingStore(server());
    await store.load();
    await store.setOptIn(true);

    await store.setOptIn(false);

    expect(store.get().current).toMatchObject({ optIn: false, names: false });
  });

  it("says why a change was refused and leaves the status as it was", async () => {
    const store = new ForwardingStore(server());
    await store.load();
    const fetcher = vi.fn<typeof fetch>(() => Promise.resolve(new Response(JSON.stringify({ error: "not on the LAN" }), { status: 403 })));
    const refused = new ForwardingStore(fetcher);
    await refused.load();
    await refused.setOptIn(true);

    expect(refused.get().phase).toEqual({ kind: "refused", reason: "not on the LAN" });
    expect(store.get().current).toMatchObject({ optIn: false });
  });

  it("says the change did not reach the server when the server is down", async () => {
    const store = new ForwardingStore(server({ down: true }));

    await store.setOptIn(true);

    expect(store.get().phase).toEqual({ kind: "refused", reason: "the change did not reach the server" });
  });

  it("sends one change at a time", async () => {
    const fetcher = server();
    const store = new ForwardingStore(fetcher);
    await store.load();
    fetcher.mockClear();

    await Promise.all([store.setOptIn(true), store.setOptIn(false)]);

    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("is a route the public demo serves", () => {
    expect(ROUTES["/api/forwarding"]).toBeNull();
  });
});
