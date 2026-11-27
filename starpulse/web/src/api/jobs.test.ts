import { describe, expect, it, vi } from "vitest";
import type { Dag } from ".";
import { followJobs, readJobs } from "./jobs";

const job = (name: string, startUrl = ""): Dag => ({ name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [], startUrl });

const sse = (...frames: [string, unknown][]) =>
  new Response(new ReadableStream({ start(c) { for (const [event, data] of frames) c.enqueue(new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)); c.close(); } }), { headers: { "content-type": "text/event-stream" } });

describe("the jobs read", () => {
  it("is one POST /api/jobs: the position, then each job with its runner's start page", async () => {
    const post = vi.fn(async () => Response.json({ position: 7, items: [job("temporal/nightly", "http://runner.test/")], error: null }));
    const jobs = await readJobs(post);
    expect(post).toHaveBeenCalledOnce();
    expect(post.mock.calls[0]).toEqual(["/api/jobs", { method: "POST", body: "{}", signal: expect.any(AbortSignal) }]);
    expect(jobs).toMatchObject({ position: 7, error: null, items: [{ name: "temporal/nightly", startUrl: "http://runner.test/" }] });
  });

  it("is null when the server refuses the read", async () => {
    expect(await readJobs(async () => new Response("no", { status: 500 }))).toBeNull();
  });
});

describe("the jobs subscription", () => {
  it("opens jobChanges from the position the list returned and hands over each change's full job list", async () => {
    const post = vi.fn(async () => sse(["next", { data: { jobChanges: { jobs: [job("a")], error: null } } }], ["next", { data: { jobChanges: { jobs: [job("a"), job("b")], error: "x: refused" } } }]));
    const seen: [string[], string | null][] = [];
    const ended = new Promise<string>((done) => followJobs(7, { jobs: (list, error) => seen.push([list.map((d) => d.name), error]), end: done }, post));
    expect(await ended).toBe("closed");
    const body = JSON.parse((post.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(body.variables).toEqual({ from: 7 });
    expect(body.query).toContain("jobChanges(from: $from)");
    expect(body.query).toMatch(/jobChanges\(from: \$from\) \{ jobs \{ name status .*runId.* steps \{ name depends .*\} stats \{ .*\} rerun \{ .*\} active \{ .*\} failed \{ .*\} closed \{ .*\} \} error domains \{.*\} cues \{.*\} pools \{.*\} \}/);
    expect(seen).toEqual([[["a"], null], [["a", "b"], "x: refused"]]);
  });

  it("says reread when the position is no longer held", async () => {
    const ended = new Promise<string>((done) => followJobs(1, { jobs: () => {}, end: done }, async () => new Response("{}", { status: 410 })));
    expect(await ended).toBe("reread");
  });

  it("stops handing over once closed", async () => {
    const seen: unknown[] = [];
    const run = followJobs(1, { jobs: (l) => seen.push(l), end: () => {} }, async () => sse(["next", { data: { jobChanges: { jobs: [job("a")], error: null } } }]));
    run.close();
    await new Promise((r) => setTimeout(r, 20));
    expect(seen).toEqual([]);
  });

  it("cancels its body when a frame does not parse, and ends the follow as closed", async () => {
    let cancelled = false;
    const body = new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode("event: next\ndata: {oops\n\n")); }, cancel() { cancelled = true; } });
    const ended = await new Promise((end) => followJobs(1, { jobs: () => {}, end }, async () => new Response(body)));
    expect(ended).toBe("closed");
    expect(cancelled).toBe(true);
  });
});
