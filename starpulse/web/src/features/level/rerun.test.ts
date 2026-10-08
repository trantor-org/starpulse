import { describe, expect, it } from "vitest";
import { RerunStore, postRerun, rerunLine, type RerunResult } from "./rerun";
import type { Dag } from "../../api";

const reply = (status: number, body: string) => async () => new Response(body, { status });

describe("posting a forced rerun", () => {
  it("posts to the DAG's rerun route and returns the new run's id", async () => {
    const seen: { url: string; init?: RequestInit }[] = [];
    const fetcher = async (url: string, init?: RequestInit) => { seen.push({ url, init }); return new Response(JSON.stringify({ runId: "r-9" }), { status: 200 }); };

    const result = await postRerun("dagu/apply-on-merge", fetcher);

    expect(result).toEqual({ ok: true, runId: "r-9" });
    expect(seen).toHaveLength(1);
    expect(seen[0].url).toBe("/api/runs/dagu/apply-on-merge/rerun");
    expect(seen[0].init?.method).toBe("POST");
  });

  it("returns the server's refusal as its reason", async () => {
    const result = await postRerun("dagu/apply-on-merge", reply(409, JSON.stringify({ error: "dagu/apply-on-merge has no unresolved failure" })));

    expect(result).toEqual({ ok: false, reason: "dagu/apply-on-merge has no unresolved failure" });
  });

  it("explains an unreachable server and a body-less failure instead of throwing", async () => {
    const down = await postRerun("dagu/a", async () => { throw new TypeError("offline"); });
    const bare = await postRerun("dagu/a", reply(502, "<html>"));

    expect(down).toMatchObject({ ok: false, reason: expect.stringContaining("could not be reached") });
    expect(bare).toMatchObject({ ok: false, reason: expect.stringContaining("502") });
  });
});

describe("the rerun store", () => {
  const settle = () => new Promise((r) => setTimeout(r, 0));

  it("keeps a DAG busy while its rerun is being asked for, and records the run it started", async () => {
    let answer: (r: RerunResult) => void = () => {};
    const posted: string[] = [], changes: number[] = [];
    const store = new RerunStore((dag) => { posted.push(dag); return new Promise((r) => { answer = r; }); }, () => changes.push(1));

    const done = store.run("dagu/apply-on-merge", 500);
    const again = store.run("dagu/apply-on-merge", 501);

    expect(store.state.busy.has("dagu/apply-on-merge")).toBe(true);
    answer({ ok: true, runId: "r-9" });
    await Promise.all([done, again]);
    expect(posted).toEqual(["dagu/apply-on-merge"]);
    expect(store.state.busy.size).toBe(0);
    expect(store.state.started["dagu/apply-on-merge"]).toEqual({ runId: "r-9", at: 500 });
    expect(changes.length).toBeGreaterThanOrEqual(2);
  });

  it("holds a refusal for the DAG until the next try, which clears it", async () => {
    const replies: RerunResult[] = [{ ok: false, reason: "dagu/a has no unresolved failure" }, { ok: true, runId: "r-1" }];
    const store = new RerunStore(async () => replies.shift()!, () => {});

    await store.run("dagu/a", 10);
    expect(store.state.refused).toEqual({ "dagu/a": "dagu/a has no unresolved failure" });
    expect(store.state.started).toEqual({});

    const next = store.run("dagu/a", 20);
    expect(store.state.refused).toEqual({});
    await next;
    await settle();
    expect(store.state.started["dagu/a"]).toEqual({ runId: "r-1", at: 20 });
  });
});

describe("the band's rerun line", () => {
  const dag = (name: string, runIds: string[]) => ({ name, active: runIds.map((runId) => ({ runId, status: "running" })) }) as unknown as Dag;

  it("says how long the forced run the page started has been running, while the snapshot still lists it", () => {
    const started = { "ci/apply": { runId: "r9", at: 1000 } };

    expect(rerunLine(started, [dag("ci/apply", ["r9"])], 1012.4)).toBe("↻ forced rerun of ci/apply running · 12 s");
    expect(rerunLine(started, [dag("ci/apply", [])], 1012)).toBeUndefined();
    expect(rerunLine(started, [dag("ci/apply", ["other"])], 1012)).toBeUndefined();
    expect(rerunLine({}, [dag("ci/apply", ["r9"])], 1012)).toBeUndefined();
  });
});
