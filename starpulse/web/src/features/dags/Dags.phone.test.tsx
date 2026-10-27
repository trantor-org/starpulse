// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Dag } from "../../api";
import type { DagData } from "./dagsModel";
import { Dags } from "./Dags";

const dag = (name: string): Dag => ({ name, status: "succeeded", runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [{ name: "scan", depends: [], status: "succeeded", kind: null, precondition: null, lock: null, last: [] }], pool: "" });
const dags = Array.from({ length: 60 }, (_, i) => dag(`runs/job-${i}`));
const data: DagData = { now: 3600, facts: {}, cpu: {}, dags, domains: [{ name: "Ops", dags: dags.map((d) => ({ name: d.name, runSafe: false })) }], pools: [], cues: [], flows: [] };

let host: HTMLDivElement, root: Root;
const phone = (narrow: boolean) => vi.stubGlobal("matchMedia", (query: string) => ({ matches: narrow && query === "(max-width: 900px)", addEventListener() {}, removeEventListener() {} }));
// the rows past the first screenful are placeholders holding the height the list estimates for them
const estimate = async () => {
  await act(async () => root.render(<Dags data={data} />));
  return host.querySelectorAll<HTMLElement>("#catalog [data-viewport-row]")[40].style.minBlockSize;
};

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

describe("the DAGs list's row-height estimate", () => {
  it("is the one-line row's above 900px", async () => {
    phone(false);
    expect(await estimate()).toBe("47px");
  });

  it("is the two-line row's at 900px and narrower, and grows with the text size", async () => {
    phone(true);
    expect(await estimate()).toBe("65px");
    document.documentElement.style.setProperty("--fs", "1.5");
    expect(await estimate()).toBe("81px");
  });
});
