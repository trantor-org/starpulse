// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Kept } from "../../shared/Kept";
import type { DagData } from "./dags";
import { Dags } from "./Dags";

const running = { runId: "r1", status: "running" as const, startedAt: "1970-01-01T00:55:00Z", step: "fix", stepStartedAt: "", steps: { fix: "running" as const } };
const data: DagData = {
  now: 3600,
  dags: [{ name: "runs/deploy", status: "succeeded", runId: "", startedAt: "", finishedAt: "", steps: [{ name: "fix", depends: [], status: "succeeded", kind: null }], pool: "", active: [running] }],
  domains: [{ name: "Ops", dags: [{ name: "runs/deploy", runSafe: true }] }],
  pools: [], cues: [], flows: [],
};

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const last = () => host.querySelector(".last")?.textContent;

describe("the DAGs view when it is left", () => {
  it("stops counting a run's seconds, and counts them again when it is shown", async () => {
    const draw = (on: boolean) => act(async () => root.render(<Kept on={on}><Dags data={data} /></Kept>));
    await draw(true);
    const before = last();
    await act(async () => void vi.advanceTimersByTime(3_000));
    expect(last()).not.toBe(before);
    await draw(false);
    const left = last();
    await act(async () => void vi.advanceTimersByTime(10_000));
    expect(last()).toBe(left);
    await draw(true);
    await act(async () => void vi.advanceTimersByTime(3_000));
    expect(last()).not.toBe(left);
  });
});
