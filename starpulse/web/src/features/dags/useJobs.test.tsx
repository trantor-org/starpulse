// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dag } from "../../api";
import { Dags } from "./Dags";
import { withJobs, type DagData } from "./dagsModel";
import { useJobs } from "./useJobs";

const job = (name: string, status: Dag["status"], over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [], startUrl: "", ...over,
});
const live = (at: string) => ({ active: [{ runId: "r", status: "running" as const, startedAt: at, step: "a", stepStartedAt: "", steps: {} }] });
const base: DagData = { now: 3600, facts: {}, cues: [], flows: [], pools: [], domains: [], dags: [] };

/** A server that answers the one read, then holds the subscription open for the test to push changes into. */
function server(first: Dag[]) {
  const calls: string[] = [];
  const waiting: ((r: ReadableStreamReadResult<Uint8Array>) => void)[] = [];
  const body = { getReader: () => ({ read: () => new Promise<ReadableStreamReadResult<Uint8Array>>((r) => waiting.push(r)) }) };
  const post = vi.fn(async (url: string) => {
    calls.push(url);
    if (url === "/api/jobs") return Response.json({ position: 5, items: first, error: null });
    return { ok: true, status: 200, body } as unknown as Response;
  });
  const push = (jobs: Dag[]) => waiting.shift()?.({ done: false, value: new TextEncoder().encode(`event: next\ndata: ${JSON.stringify({ data: { jobChanges: { jobs, error: null } } })}\n\n`) });
  return { post, calls, push };
}

let host: HTMLDivElement, root: Root;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const panes = () => Object.fromEntries([...host.querySelectorAll<HTMLElement>("#stage .drow")].map((r) => [r.dataset.dag!, r.dataset.pane!]));

function Page({ post }: { post: ReturnType<typeof server>["post"] }) {
  const { jobs } = useJobs(true, post);
  return <Dags data={withJobs(base, jobs ?? [])} />;
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the Jobs page after its first load", () => {
  it("makes no request while job deltas arrive, and moves a job between Processing and Just finished on each", async () => {
    const s = server([job("temporal/nightly", "running", live("1970-01-01T00:50:00Z"))]);
    await act(async () => root.render(<Page post={s.post} />));
    await flush();
    expect(s.calls).toEqual(["/api/jobs", "/graphql"]);
    expect(panes()["temporal/nightly"]).toBe("processing");

    await act(async () => s.push([job("temporal/nightly", "succeeded", { runId: "r1", finishedAt: "1970-01-01T00:59:00Z" })]));
    await flush();
    expect(panes()["temporal/nightly"]).toBe("idle");

    await act(async () => s.push([job("temporal/nightly", "running", live("1970-01-01T00:59:30Z")), job("woodpecker/push", "succeeded")]));
    await flush();
    expect(panes()).toMatchObject({ "temporal/nightly": "processing", "woodpecker/push": "idle" });
    expect(s.calls).toEqual(["/api/jobs", "/graphql"]);
  });
});
