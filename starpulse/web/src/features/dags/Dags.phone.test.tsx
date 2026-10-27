// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dag } from "../../api";
import type { DagData } from "./dagsModel";
import { Dags } from "./Dags";

const dag = (name: string, status: Dag["status"] = "succeeded"): Dag => ({ name, status, runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [{ name: "scan", depends: [], status: "succeeded", kind: null, precondition: null, lock: null, last: [] }], pool: "" });
const dags = [dag("runs/job-0", "running"), dag("runs/job-1"), dag("runs/job-2")];
const data: DagData = { now: 3600, facts: {}, cpu: {}, dags, domains: [{ name: "Ops", dags: dags.map((d) => ({ name: d.name, runSafe: false })) }], pools: [], cues: [], flows: [] };

let host: HTMLDivElement, root: Root;
const phone = (narrow: boolean) => vi.stubGlobal("matchMedia", (query: string) => ({ matches: narrow && query === "(max-width: 900px)", addEventListener() {}, removeEventListener() {} }));
const place = (name: string) => {
  const el = host.querySelector<HTMLElement>(`.drow[data-dag="${name}"]`)!;
  return ["--c", "--hs", "--s"].map((k) => el.style.getPropertyValue(k)).join(" ");
};
const draw = () => act(async () => root.render(<Dags data={data} />));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.clear();
  document.documentElement.style.removeProperty("--fs");
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("the DAGs view's panes by width", () => {
  it("sets Idle beside Processing above 900px, both from the top", async () => {
    phone(false);
    await draw();
    expect(place("runs/job-0")).toBe("0 1 0");
    expect(place("runs/job-1")).toBe("1 1 0");
    expect(host.querySelector<HTMLElement>("#stage .dstage")!.style.getPropertyValue("--cols")).toBe("2");
  });

  it("stacks Idle under Processing at 900px and narrower, one header slot lower", async () => {
    phone(true);
    await draw();
    expect(place("runs/job-0")).toBe("0 1 0");
    expect(place("runs/job-1")).toBe("0 2 1");
    expect(place("runs/job-2")).toBe("0 2 2");
    expect(host.querySelector<HTMLElement>("#stage .dstage")!.style.getPropertyValue("--cols")).toBe("1");
  });

  it("keeps a slot for the empty Processing pane's hint, so Idle starts below it", async () => {
    phone(true);
    const idle = { ...data, dags: [dag("runs/job-0")] };
    await act(async () => root.render(<Dags data={idle} />));
    expect(host.querySelector(".phint")!.textContent).toBe("Nothing is running");
    expect(place("runs/job-0")).toBe("0 2 1");
  });
});
