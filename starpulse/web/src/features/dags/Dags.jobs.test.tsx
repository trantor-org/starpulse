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
