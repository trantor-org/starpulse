// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { DagData } from "../features/dags/dags";
import type { HudStore } from "../render/hud";

// the canvas renderer needs a browser's 2D context; the navigator around it does not. It hands the HUD store to the test, which writes what a snapshot would.
const stores: HudStore[] = [];
vi.mock("../render/renderer", async (original) => ({
  ...(await original<typeof import("../render/renderer")>()),
  renderer: (_canvas: unknown, store: HudStore) => {
    stores.push(store);
    return new Proxy({}, { get: () => () => {} });
  },
}));

const dagData: DagData = {
  now: 100,
  dags: [
    { name: "runs/pr-watch", status: "succeeded", runId: "", startedAt: "", finishedAt: "1970-01-01T00:01:00Z", steps: [{ name: "scan", depends: [], status: "succeeded", kind: null }], pool: "runs/main" },
    { name: "runs/sweep", status: "not_started", runId: "", startedAt: "", finishedAt: "", steps: [{ name: "scan", depends: [], status: "not_started", kind: null }] },
  ],
  domains: [{ name: "Board", dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/sweep", runSafe: false }] }],
  pools: [{ name: "runs/main", cap: 2, running: 1, queued: 0 }],
  cues: [],
  flows: [],
};

let host: HTMLDivElement, root: Root;
const q = (sel: string) => host.querySelector<HTMLElement>(sel);
const views = () => [...host.querySelectorAll<HTMLElement>("#nav section.views:not(.admin-sec) .node")];
const dagsNode = () => views().find((n) => n.title === "DAGs")!;

beforeEach(async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })));
  localStorage.clear();
  stores.length = 0;
  history.replaceState(null, "", "/?view=constellation");
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  await act(async () => root.render(<App />));
  act(() => stores[0].set({ dags: dagData.dags.map((d) => d.name), dagData, pools: dagData.pools }));
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  document.body.className = "";
  vi.unstubAllGlobals();
});

describe("the navigator's DAGs entry", () => {
  it("lists DAGs under Views, after Kanban, with the constellation glyph and the DAG count", () => {
    expect(views().slice(0, 3).map((n) => n.title)).toEqual(["Star Map", "Kanban", "DAGs"]);
    expect(dagsNode().querySelectorAll("svg.dg-glyph circle")).toHaveLength(4);
    expect(dagsNode().querySelector(".n")!.textContent).toBe("2");
  });

  it("opens the DAGs view when selected, and puts it in the address", () => {
    act(() => dagsNode().click());

    expect(q("#dg")).not.toBeNull();
    expect(q("#dg header .title")!.textContent).toBe("DAGs");
    expect(dagsNode().className).toContain("on here");
    expect(document.body.classList.contains("dags")).toBe(true);
    expect(location.search).toBe("?view=dags");
  });
});

describe("the DAGs view's navigator and legend", () => {
  beforeEach(() => act(() => dagsNode().click()));

  it("shows the Queues section, and not the Star Map's layers, DAG domains or search", () => {
    expect(q("#queues")!.textContent).toContain("main");
    expect(q("#layers")).toBeNull();
    expect(q("#cons")).toBeNull();
    expect(q("#q")).toBeNull();
    expect(q("#nav .note")!.textContent).toContain("Layers belong to the Star Map");
  });

  it("shows the DAG legend in the rail", () => {
    const legend = q("#legend")!.textContent!;

    expect(legend).toContain("last run failed");
    expect(legend).toContain("run-safe");
    expect(legend).not.toContain("checks pass");
  });
});

describe("the Star Map's navigator and legend", () => {
  it("lists no DAGs and no Queues, and the legend has no DAG entries", () => {
    expect(q("#cons")).toBeNull();
    expect(q("#queues")).toBeNull();
    expect([...host.querySelectorAll("#nav h3")].map((h) => h.textContent)).toEqual(["Views"]);
    expect(q("#legend")!.textContent).not.toMatch(/\bok\b|failed|runnable/);
  });

  it("names no DAG in its search, and finds none", () => {
    expect(q("#q")!.getAttribute("aria-label")).not.toContain("DAG");
  });
});

describe("a DAG's line in the Recent rail", () => {
  const feed = [
    { key: "t", at: 2, time: "12:01", who: "TASK-1", what: "claimed", where: "Ready → In progress", task: "TASK-1" },
    { key: "d", at: 1, time: "12:00", who: "runs/pr-watch", what: "finished", where: "ok", tone: "ok" as const, dag: "runs/pr-watch" },
  ];
  const lines = () => [...host.querySelectorAll<HTMLElement>("#feed > div")];
  const hover = (el: HTMLElement) => act(() => void el.dispatchEvent(new MouseEvent("pointerover", { bubbles: true })));
  beforeEach(() => act(() => stores[0].set({ feed })));

  it("is inert on the Star Map, which draws no DAG", () => {
    expect(lines().map((l) => l.classList.contains("go"))).toEqual([true, false]);
  });

  it("lights the DAG's row in the DAGs view while hovered, and its click opens the DAG's modal", () => {
    act(() => dagsNode().click());
    const [task, dag] = lines();

    expect([task.classList.contains("go"), dag.classList.contains("go")]).toEqual([false, true]);
    hover(dag);
    expect([...host.querySelectorAll<HTMLElement>("#dg .trow.spot")].map((r) => r.dataset.dag)).toEqual(["runs/pr-watch"]);
    act(() => void dag.dispatchEvent(new MouseEvent("pointerout", { bubbles: true })));
    expect(q("#dg .trow.spot")).toBeNull();

    expect(q("#dg .dgm")).toBeNull();
    act(() => dag.click());
    expect(q('.dgm[role="dialog"]')!.getAttribute("aria-label")).toBe("runs/pr-watch");
  });
});
