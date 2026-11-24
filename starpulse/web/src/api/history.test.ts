import { describe, expect, it, vi } from "vitest";
import { createHistory } from "./history";

const rows = [{ at: 1, from: null, to: "Ready" }];
const reply = (body: unknown, ok = true) => Promise.resolve({ ok, json: () => Promise.resolve(body) });
const task = (fields: object) => reply({ data: { task: fields } });
const sent = (f: { mock: { calls: unknown[][] } }) =>
  f.mock.calls.map(([url, init]) => ({ url, ...JSON.parse((init as RequestInit).body as string) }));
const settle = () => new Promise((r) => setTimeout(r, 0));

function rig(fetch: (url: string, init: RequestInit) => Promise<{ ok: boolean; json(): Promise<unknown> }>) {
  let clock = 1000;
  const onChange = vi.fn(), f = vi.fn(fetch);
  const history = createHistory({ onChange, fetch: f, now: () => clock, ttl: 30 });
  return { history, onChange, f, tick: (s: number) => (clock += s) };
}

describe("the history cache", () => {
  it("answers loading, reads the task's lane path once, tells the page, then answers the path", async () => {
    const { history, onChange, f } = rig(() => task({ lanePath: rows }));

    expect(history.lane("PROJ-7")).toBe("loading");
    expect(history.lane("PROJ-7")).toBe("loading");
    await settle();

    expect(f).toHaveBeenCalledTimes(1);
    expect(sent(f)).toMatchObject([{ url: "/graphql", variables: { id: "PROJ-7" } }]);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(history.lane("PROJ-7")).toEqual(rows);
  });

  it("reads a machine path with its step total, keyed by flow", async () => {
    const { history, f } = rig(() => task({ machinePath: { path: [], steps: 9 } }));

    history.machine("PROJ-7", "in-progress");
    await settle();

    expect(sent(f)).toMatchObject([{ url: "/graphql", variables: { id: "PROJ-7", machine: "in-progress" } }]);
    expect(history.machine("PROJ-7", "in-progress")).toEqual({ path: [], steps: 9 });
    expect(history.lane("PROJ-7")).toBe("loading");
  });

  it("keeps showing the old path while a stale one is read again, and not before it is stale", async () => {
    const { history, f, tick } = rig(() => task({ lanePath: rows }));
    history.lane("PROJ-7");
    await settle();

    tick(10);
    history.lane("PROJ-7");
    expect(f).toHaveBeenCalledTimes(1);

    tick(30);
    expect(history.lane("PROJ-7")).toEqual(rows);
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("answers unavailable when the read fails, and tries again once it is stale", async () => {
    const { history, onChange, f, tick } = rig(() => reply({ error: "no database" }, false));
    history.lane("PROJ-7");
    await settle();

    expect(history.lane("PROJ-7")).toBe("unavailable");
    expect(onChange).toHaveBeenCalledTimes(1);
    tick(31);
    history.lane("PROJ-7");
    expect(f).toHaveBeenCalledTimes(2);
  });

  it("answers unavailable when the reply carries errors, and empty for a task the board does not hold", async () => {
    const bad = rig(() => reply({ data: null, errors: [{ message: "unknown machine x" }] }));
    bad.history.machine("PROJ-7", "x");
    const none = rig(() => reply({ data: { task: null } }));
    none.history.lane("PROJ-7");
    await settle();

    expect(bad.history.machine("PROJ-7", "x")).toBe("unavailable");
    expect(none.history.lane("PROJ-7")).toEqual([]);
  });

  it("answers unavailable when the request itself throws", async () => {
    const { history } = rig(() => Promise.reject(new Error("offline")));
    history.lane("PROJ-7");
    await settle();

    expect(history.lane("PROJ-7")).toBe("unavailable");
  });

  it("sends the task and machine ids as variables, never spliced into the query", async () => {
    const { history, f } = rig(() => task({ lanePath: rows, machinePath: { path: [], steps: 0 } }));
    history.machine("A&B", "x y");
    history.lane("C#1");
    await settle();

    expect(sent(f).map((c) => c.variables)).toEqual([{ id: "A&B", machine: "x y" }, { id: "C#1" }]);
  });

  it("reads a task's last 24h of machine events for the drill-in replay", async () => {
    const events = [{ at: 5, machine: "build", event: "BUILD_DONE", from: "running", to: "done" }];
    const { history, f } = rig(() => task({ events }));

    expect(history.replay("PROJ-7")).toBe("loading");
    await settle();

    expect(sent(f)).toMatchObject([{ url: "/graphql", variables: { id: "PROJ-7", since: 1000 - 86400 } }]);
    expect(history.replay("PROJ-7")).toEqual(events);
  });
});
