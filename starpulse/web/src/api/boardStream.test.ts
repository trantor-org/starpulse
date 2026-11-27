import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOST_MS, QUIET_MS, RETRY_CAP_MS } from "./retry";
import { openStream } from "./stream";
import type { Snapshot } from ".";

const state = (id: string, initial = false, final = false) => ({ id, name: id, initial, final, role: null, priority: 0 });
const MACHINE = { name: "board", states: [state("ready", true), state("done", false, true)], transitions: [], submachines: [], launches: {}, writers: {} };
const task = (id: string, lane: string) => ({
  id, title: id, lane, profile: "p", impact: "low", urgency: "low", tier: "standard", source: "", assignee: null, labels: [], milestone: "", type: "task",
  dependencies: [], workable: true, createdAt: 100, movedAt: 200, description: "", prs: [], lanePath: [], criteria: [], released: null,
  sessionActivity: null, skill: null, phase: null, substate: null, planRevisions: 0,
});
const READ = {
  tasks: { position: 7, items: [task("TASK-1", "ready")], settled: [], milestoneDone: [], archivedToday: 0, machineTasks: [] },
  board: { columns: MACHINE.states, roles: { initial: "ready", final: "done", startable: [], lanes: ["ready"] }, machines: [MACHINE], error: null },
};
const JOBS = { items: [], domains: [], cues: [], pools: [], error: null, position: 3 };
const HEALTH = { components: [{ name: "board", ready: true, detail: "" }], build: "b1", restarting: false, at: 1000 };

const PING_MS = 15_000; // the server's `_PING_S`: every subscription sends a byte at least this often
const PING = new TextEncoder().encode(": ping\n\n");

/** A server's side of the page's requests: the reads answer at once, each subscription is a body the test pushes `next` frames into and that pings every PING_MS until `silent`. */
function server(read: typeof READ = READ) {
  const seen: string[] = [];
  const open: Record<string, ReadableStreamDefaultController<Uint8Array>> = {};
  const pings: Record<string, () => void> = {};
  const gone = new Set<string>();
  const control = { down: false, failRead: false, hold: false, hang: false, silent: false, stall: false };
  const never = (init?: RequestInit) => new Promise<Response>((_, fail) => init?.signal?.addEventListener("abort", () => fail(init.signal?.reason)));
  const holds: (() => void)[] = [];
  const post = async (url: string, init?: RequestInit) => {
    if (control.down) throw new Error("unreachable");
    const query = url === "/graphql" ? (JSON.parse(String(init?.body)).query as string) : url;
    const field = /subscription[^{]*{\s*(\w+)/.exec(query)?.[1];
    seen.push(field ?? (url === "/graphql" ? "read" : url));
    if (!field && url === "/graphql") {
      if (control.hang) return never(init);
      if (control.failRead || control.hold) await new Promise<void>((go) => holds.push(go));
      if (control.failRead) return new Response("{}", { status: 500 });
    }
    if (field && gone.delete(field)) return new Response("{}", { status: 410 });
    if (field && control.stall) return never(init);
    if (field) {
      let ping: ReturnType<typeof setInterval>;
      const quiet = () => clearInterval(ping);
      return new Response(new ReadableStream<Uint8Array>({
        start: (c) => {
          [open[field], pings[field], ping] = [c, quiet, setInterval(() => control.silent || c.enqueue(PING), PING_MS)];
          // as fetch errors an aborted body; one `end` already closed has nothing left to error
          init?.signal?.addEventListener("abort", () => {
            quiet();
            try { c.error(init.signal?.reason); } catch { /* closed */ }
          });
        },
        cancel: quiet,
      }));
    }
    if (url === "/api/jobs") return Response.json(JOBS);
    return Response.json({ data: read });
  };
  const push = (field: string, data: unknown) =>
    open[field].enqueue(new TextEncoder().encode(`event: next\ndata: ${JSON.stringify({ data: { [field]: data } })}\n\n`));
  const end = (field: string) => {
    pings[field]();
    open[field].close();
  };
  const release = () => holds.splice(0).forEach((go) => go());
  return { post, seen, push, end, gone, control, release, reads: () => seen.filter((q) => q === "read").length };
}

const lanes = (sky: Snapshot) => sky.flows.find((f) => f.name === "board")!.agents.map((a) => `${a.id}:${a.state}`);

describe("openStream", () => {
  beforeEach(() => void vi.useFakeTimers());
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("reads the board once, then fires no request while changes arrive over its subscriptions, whatever the clock", async () => {
    const s = server();
    const skies: Snapshot[] = [];
    const stream = openStream({ snapshot: (sky) => void skies.push(sky), live: () => {} }, s.post);
    await vi.advanceTimersByTimeAsync(0);
    s.push("health", HEALTH);
    await vi.advanceTimersByTimeAsync(0);
    expect(lanes(skies.at(-1)!)).toEqual(["TASK-1:ready"]);

    const requests = s.seen.length;
    s.push("taskChanges", { id: "TASK-1", machine: "board", task: task("TASK-1", "done"), settled: null, machineTask: null });
    await vi.advanceTimersByTimeAsync(0);
    expect(lanes(skies.at(-1)!)).toEqual(["TASK-1:done"]);
    s.push("taskChanges", { id: "TASK-2", machine: "board", task: task("TASK-2", "ready"), settled: null, machineTask: null });
    await vi.advanceTimersByTimeAsync(24 * 3600 * 1000);
    expect(lanes(skies.at(-1)!)).toEqual(["TASK-1:done", "TASK-2:ready"]);
    expect(s.seen.length).toBe(requests);
    stream.close();
  });

  it("asks neither its first read nor its task changes for pauseReason or readable, which no card draws", async () => {
    const queries: string[] = [];
    const s = server();
    const stream = openStream({ snapshot: () => {}, live: () => {} }, (url, init) => {
      if (url === "/graphql") queries.push(JSON.parse(String(init?.body)).query);
      return s.post(url, init);
    });
    await vi.advanceTimersByTimeAsync(0);
    const asked = queries.filter((q) => /\btasks\b|taskChanges/.test(q));
    expect(asked.some((q) => q.includes("taskChanges"))).toBe(true);
    expect(asked.some((q) => q.startsWith("query"))).toBe(true);
    for (const q of asked) expect(q).not.toMatch(/\b(pauseReason|readable)\b/);
    stream.close();
  });

  const settle = () => vi.advanceTimersByTimeAsync(0);
  const open = async (read = READ, handlers: Partial<Parameters<typeof openStream>[0]> = {}) => {
    const s = server(read);
    const skies: Snapshot[] = [];
    const stream = openStream({ snapshot: (sky) => void skies.push(sky), live: () => {}, ...handlers }, s.post);
    await settle();
    return { s, skies, stream, last: () => skies.at(-1)! };
  };
  const health = (over: Partial<typeof HEALTH> = {}, ready = true) => ({ ...HEALTH, components: [{ name: "board", ready, detail: "" }], ...over });

  describe("its link", () => {
    it("is live from the first health event, and any of its streams ending drops the connection, which reads the board again at once", async () => {
      for (const field of ["health", "taskChanges", "jobChanges"]) {
        const links: string[] = [];
        const { s, stream } = await open(READ, { link: (l) => void links.push(l) });
        s.push("health", health());
        await settle();
        expect(links).toEqual(["live"]);

        s.end(field);
        await settle();

        expect([field, s.reads(), links]).toEqual([field, 2, ["live", "retrying"]]);
        stream.close();
      }
    });

    it("holds the Board it drew through a drop as stale, until the server's whole one is handed over", async () => {
      const links: string[] = [];
      const { s, skies, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      await settle();
      s.end("jobChanges");
      await settle();
      const before = skies.length;

      s.push("health", health({}, false));
      await settle();
      expect([links, skies.length]).toEqual([["live", "retrying", "stale"], before]);

      s.push("health", health());
      await settle();
      expect([links, skies.length, skies.at(-1)!.reading]).toEqual([["live", "retrying", "stale", "live"], before + 1, false]);
      stream.close();
    });

    it("backs off while the server stays away, says offline once it has been gone for LOST_MS, and reconnects when it returns", async () => {
      const links: string[] = [];
      const { s, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      await settle();
      s.control.down = true;
      s.end("health");
      await vi.advanceTimersByTimeAsync(LOST_MS + 1);
      expect(links).toEqual(["live", "retrying", "offline"]);

      s.control.down = false;
      await vi.advanceTimersByTimeAsync(RETRY_CAP_MS);
      s.push("health", health());
      await settle();

      expect(links).toEqual(["live", "retrying", "offline", "stale", "live"]);
      stream.close();
    });

    it("drops a connection whose streams go QUIET_MS without a byte and reads the board again, while pinging streams stay live", async () => {
      const links: string[] = [];
      const { s, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      await settle();
      await vi.advanceTimersByTimeAsync(10 * QUIET_MS);
      expect([s.reads(), links]).toEqual([1, ["live"]]);

      s.control.silent = true;
      await vi.advanceTimersByTimeAsync(QUIET_MS);

      expect([s.reads(), links]).toEqual([2, ["live", "retrying"]]);
      stream.close();
    });

    it("drops a reconnect whose subscriptions never answer once QUIET_MS pass, and reads the board again", async () => {
      const links: string[] = [];
      const { s, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      await settle();
      s.control.stall = true;
      s.end("taskChanges");
      await settle();
      expect(s.reads()).toBe(2);

      await vi.advanceTimersByTimeAsync(QUIET_MS + RETRY_CAP_MS);

      expect([s.reads(), links]).toEqual([3, ["live", "retrying", "offline"]]); // down past LOST_MS by then
      stream.close();
    });

    it("says restarting from the server's announcement, and through the drop that follows", async () => {
      const links: string[] = [];
      const { s, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      s.push("health", health({ restarting: true }));
      await settle();
      s.end("health");
      await settle();

      expect(links).toEqual(["live", "restarting"]);
      stream.close();
    });

    it("reads again at once, with no wait, when the server no longer holds the position a subscription asked from", async () => {
      const links: string[] = [];
      const { s, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      await settle();
      s.gone.add("taskChanges");
      s.end("jobChanges");
      await settle();

      expect([s.reads(), links]).toEqual([3, ["live", "retrying"]]);
      stream.close();
    });

    it("keeps backing off while the server answers its health but never its board, resetting only once a whole read succeeds", async () => {
      const s = server();
      s.control.failRead = true;
      const stream = openStream({ snapshot: () => {}, live: () => {} }, s.post);
      await settle();
      for (const reads of [2, 2]) {
        s.push("health", health());
        await settle();
        s.release();
        await settle();
        expect(s.reads()).toBe(reads);
      }

      await vi.advanceTimersByTimeAsync(250);
      expect(s.reads()).toBe(3);
      stream.close();
    });

    it("does not hand over the Board it held before a drop as the new connection's, when that connection's health arrives ahead of its read", async () => {
      const links: string[] = [];
      const { s, skies, stream } = await open(READ, { link: (l) => void links.push(l) });
      s.push("health", health());
      await settle();
      s.control.hold = true;
      s.end("jobChanges");
      await settle();
      const before = skies.length;

      s.push("health", health());
      await settle();
      expect([links, skies.length]).toEqual([["live", "retrying", "stale"], before]);

      s.control.hold = false;
      s.release();
      await settle();
      expect([links, skies.length]).toEqual([["live", "retrying", "stale", "live"], before + 1]);
      stream.close();
    });

    it("gives up on a board read the server never answers, and reads again", async () => {
      const timeouts: AbortController[] = [];
      vi.spyOn(AbortSignal, "timeout").mockImplementation(() => {
        const timer = new AbortController();
        timeouts.push(timer);
        return timer.signal;
      });
      const s = server();
      s.control.hang = true;
      const stream = openStream({ snapshot: () => {}, live: () => {} }, s.post);
      await settle();
      expect(s.reads()).toBe(1);

      timeouts[0]?.abort(new DOMException("timed out", "TimeoutError"));
      await settle();

      expect(s.reads()).toBe(2);
      stream.close();
    });
  });

  describe("its health", () => {
    it("hands the first Board over flagged reading, and again without the flag once the server's board is ready", async () => {
      const { s, skies, stream } = await open();
      expect(skies.map((k) => k.reading)).toEqual([true]);

      s.push("health", health());
      await settle();

      expect(skies.map((k) => k.reading)).toEqual([true, false]);
      stream.close();
    });

    it("reports a build other than the one the page opened with, once, and only after the server has read its board", async () => {
      const builds: string[] = [];
      const { s, stream } = await open(READ, { build: (b) => void builds.push(b) });
      s.push("health", health());
      s.push("health", health({ build: "b2" }, false));
      await settle();
      expect(builds).toEqual([]);

      s.push("health", health({ build: "b2" }));
      s.push("health", health({ build: "b2" }));
      await settle();

      expect(builds).toEqual(["b2"]);
      stream.close();
    });

    it("hands over the clock offset its `at` gives, each time it says", async () => {
      const skews: number[] = [];
      const { s, stream } = await open(READ, { clock: (k) => void skews.push(k) });

      s.push("health", health({ at: Date.now() / 1000 + 100 }));
      await settle();
      s.push("health", health({ at: Date.now() / 1000 - 5 }));
      await settle();

      expect(skews).toEqual([100, -5]);
      stream.close();
    });
  });

  describe("its changes", () => {
    const gone = (id: string) => ({ id, machine: "board", task: null, settled: null, machineTask: null });
    const settledAs = (id: string, state: string, milestone: string) => ({ id, machine: "board", task: null, machineTask: null, settled: { id, state, at: 300, created: 100, title: id, model: "", milestone, labels: [] } });
    const shown = async () => {
      const it = await open();
      it.s.push("health", health());
      await settle();
      return it;
    };

    it("counts a task the board no longer holds and no settled entry shows as archived, once, and a task that settles in the final lane as completed in its milestone", async () => {
      const { s, last, stream } = await shown();

      s.push("taskChanges", gone("TASK-1"));
      s.push("taskChanges", gone("TASK-1"));
      await settle();
      expect([lanes(last()), last().archived_today, last().milestone_done]).toEqual([[], 1, {}]);

      s.push("taskChanges", { id: "TASK-2", machine: "board", task: task("TASK-2", "ready"), settled: null, machineTask: null });
      s.push("taskChanges", settledAs("TASK-2", "done", "m1"));
      await settle();

      expect([lanes(last()), last().archived_today, last().milestone_done, last().settled["TASK-2"]?.state]).toEqual([[], 1, { m1: 1 }, "done"]);
      s.push("taskChanges", { id: "TASK-2", machine: "board", task: task("TASK-2", "ready"), settled: null, machineTask: null });
      await settle();
      expect([lanes(last()), last().milestone_done, last().settled]).toEqual([["TASK-2:ready"], { m1: 0 }, {}]);
      stream.close();
    });

    it("reads a task's pull requests off the task, and drops them with it", async () => {
      const { s, last, stream } = await shown();
      const pr = { repo: "o/r", number: 5, state: "OPEN", isDraft: false, mergeable: "MERGEABLE", checks: "pass", threads: 0, mergedAt: null, mergeSha: null };

      s.push("taskChanges", { id: "TASK-1", machine: "board", task: { ...task("TASK-1", "ready"), prs: [pr] }, settled: null, machineTask: null });
      await settle();
      expect(last().pulls?.["TASK-1"]?.map((p) => [p.url, p.merged])).toEqual([["https://github.com/o/r/pull/5", false]]);

      s.push("taskChanges", gone("TASK-1"));
      await settle();
      expect(last().pulls).toEqual({});
      stream.close();
    });

    it("hands over a pull request whose checks change while its task's card stays as it was", async () => {
      const { s, last, skies, stream } = await shown();
      const pr = { repo: "o/r", number: 5, state: "OPEN", isDraft: false, mergeable: "MERGEABLE", checks: "pending", threads: 0, mergedAt: null, mergeSha: null };
      const change = (checks: string) => ({ id: "TASK-1", machine: "board", task: { ...task("TASK-1", "ready"), prs: [{ ...pr, checks }] }, settled: null, machineTask: null });
      s.push("taskChanges", change("pending"));
      await settle();
      const before = skies.length;

      s.push("taskChanges", change("pass"));
      await settle();

      expect([skies.length, last().pulls?.["TASK-1"]?.[0].checks]).toEqual([before + 1, "pass"]);
      stream.close();
    });

    it("names each task the scheduler runs that cite it on its card, as the jobs change", async () => {
      const { s, last, stream } = await shown();
      const run = { runId: "r1", task: "TASK-1", startedAt: "2026-11-25T01:00:00Z", status: "running", url: "http://t/r1" };

      s.push("jobChanges", { jobs: [{ name: "deliver", active: [run], failed: [], closed: [] }], error: "temporal down", domains: [{ name: "Ops", dags: [{ name: "deliver" }] }], cues: [], pools: [] });
      await settle();

      expect(last().flows[0].agents[0].runs).toEqual([{ startedAt: run.startedAt, status: "running", url: "http://t/r1" }]);
      expect([last().dags?.map((d) => d.name), last().domains?.map((d) => d.name), last().error]).toEqual([["deliver"], ["Ops"], "temporal down"]);
      stream.close();
    });

    it("places a machine's task on that machine, replacing the place it held, and leaves the Board alone", async () => {
      const lifecycle = { ...MACHINE, name: "build", states: [state("fetch", true), state("done", false, true)] };
      const { s, last, stream } = await open({ ...READ, board: { ...READ.board, machines: [MACHINE, lifecycle] } });
      s.push("health", health());
      await settle();
      const run = (at: string) => ({ id: "s1", machine: "build", task: null, settled: null, machineTask: { id: "s1", title: "s", model: "", task: "TASK-1", state: at, steps: [], active: 5, trail: [] } });
      const agents = () => last().flows.find((f) => f.name === "build")!.agents.map((a) => `${a.id}:${a.state}`);

      s.push("taskChanges", run("fetch"));
      await settle();
      expect([agents(), lanes(last())]).toEqual([["s1:fetch"], ["TASK-1:ready"]]);

      s.push("taskChanges", run("done"));
      await settle();
      expect(agents()).toEqual(["s1:done"]);
      stream.close();
    });
  });
});
