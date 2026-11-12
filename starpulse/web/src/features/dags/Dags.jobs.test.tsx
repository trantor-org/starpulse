// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DagData } from "./dagsModel";
import { Dags } from "./Dags";
import type { Dag, RunStatus } from "../../api";

const job = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [], ...over,
});
const data: DagData = {
  now: 3600, facts: {}, cpu: {}, cues: [], flows: [], pools: [], domains: [],
  dags: [
    job("temporal/task_lifecycle", "running", {
      runId: "r1", startedAt: "1970-01-01T00:50:00Z",
      active: [{ runId: "r1", status: "running", startedAt: "1970-01-01T00:50:00Z", step: "ci_head", stepStartedAt: "", steps: { ci_head: "running" }, task: "TASK-9", attempt: 2, failure: "ci_head exited 2" }],
    }),
    job("temporal/task_phases", "succeeded", {
      failed: [{ runId: "r0", task: "TASK-8", url: "http://t/r0", status: "failed", startedAt: "", finishedAt: "1970-01-01T00:30:00Z", params: {}, steps: { park_task: "failed" }, attempt: 3, failure: "park exited 4" }],
    }),
    job("temporal/AlertInvestigationWorkflow", "not_started"),
    job("woodpecker/pull_request", "failed", {
      runId: "30", startedAt: "1970-01-01T00:20:00Z", finishedAt: "1970-01-01T00:30:00Z",
      active: [{ runId: "31", url: "http://ci/repos/1/pipeline/31", status: "running", startedAt: "1970-01-01T00:55:00Z", step: "tests", stepStartedAt: "", steps: { tests: "running" }, task: "TASK-13936", pr: 9052, commit: "abcdef0123456789", attempt: null, failure: null }],
      closed: [{ runId: "30", url: "http://ci/repos/1/pipeline/30", status: "failed", startedAt: "1970-01-01T00:20:00Z", finishedAt: "1970-01-01T00:30:00Z", params: {}, steps: { tests: "failed" }, task: "TASK-12440", pr: 9050, commit: "1152cc200628", attempt: null, failure: "step tests exited 2" },
        { runId: "29", url: "http://ci/repos/1/pipeline/29", status: "succeeded", startedAt: "1970-01-01T00:10:00Z", finishedAt: "1970-01-01T00:14:00Z", params: {}, steps: {}, task: null, pr: null, commit: "0000000ffff", attempt: null, failure: null }],
    }),
    job("woodpecker/push", "succeeded"),
  ],
};

let host: HTMLDivElement, root: Root;
const draw = async () => { await act(async () => root.render(<Dags data={data} post={vi.fn()} />)); };
const row = (n: string) => [...host.querySelectorAll<HTMLElement>("#stage .drow")].find((r) => r.dataset.dag === n)!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

describe("a Temporal job in the Jobs view", () => {
  it("shows the running job's task, activity, attempt and last failure on its row", async () => {
    await draw();
    expect(row("temporal/task_lifecycle").querySelector(".sub")!.textContent).toBe("TASK-9 · ci_head · attempt 2 · ci_head exited 2");
  });

  it("shows a job's newest failed run on its row while it is not running, and the default line when it has none", async () => {
    await draw();
    expect(row("temporal/task_phases").querySelector(".sub")!.textContent).toBe("failed TASK-8 · park_task · attempt 3 · park exited 4");
    expect(row("temporal/AlertInvestigationWorkflow").querySelector(".sub")!.textContent).toBe("manual · no pool");
  });

  it("lists its running and failed runs in the modal", async () => {
    await draw();
    await act(async () => { row("temporal/task_phases").click(); });
    const runs = host.querySelector(".dgm")!.textContent!;
    expect(runs).toContain("TASK-8 · park_task · attempt 3 · park exited 4");
    expect(host.querySelector(".dgm .bad")!.textContent).toBe("failed");
  });
});

describe("a Woodpecker job in the Jobs view", () => {
  const lines = () => [...host.querySelectorAll<HTMLElement>(".dgm .runs .k")].map((x) => x.textContent);
  const open = async () => { await draw(); await act(async () => { row("woodpecker/pull_request").click(); }); };

  it("lists its running and closed pipelines in the modal with status, task, pull request, commit, duration and a link", async () => {
    await open();
    expect(lines()).toEqual([
      "running TASK-13936 · #9052 · abcdef0 · tests · 5m 0s · run ↗",
      "failed TASK-12440 · #9050 · 1152cc2 · tests · step tests exited 2 · 10m 0s · run ↗",
      "succeeded 0000000 · 4m 0s · run ↗",
    ]);
    expect([...host.querySelectorAll<HTMLAnchorElement>(".dgm .runs a")].map((a) => a.getAttribute("href"))).toEqual([
      "http://ci/repos/1/pipeline/31", "http://ci/repos/1/pipeline/30", "http://ci/repos/1/pipeline/29",
    ]);
  });

  it("lists the succeeded pipelines of a job that never failed, which the failed list leaves out", async () => {
    await draw();
    await act(async () => { row("woodpecker/push").click(); });
    expect(host.querySelector(".dgm")!.textContent).not.toContain("Runs");
  });

  it("still draws the other jobs when a source reports no jobs", async () => {
    await act(async () => root.render(<Dags data={{ ...data, dags: data.dags.filter((d) => !d.name.startsWith("woodpecker/")) }} post={vi.fn()} />));
    expect(row("temporal/task_lifecycle")).toBeDefined();
    expect(row("woodpecker/pull_request")).toBeUndefined();
  });
});
