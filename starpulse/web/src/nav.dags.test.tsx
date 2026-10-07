// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { DagData } from "./dags";
import type { HudStore } from "./hud";

// the canvas renderer needs a browser's 2D context; the navigator around it does not. It hands the HUD store to the test, which writes what a snapshot would.
const stores: HudStore[] = [];
vi.mock("./renderer", async (original) => ({
  ...(await original<typeof import("./renderer")>()),
  renderer: (_canvas: unknown, store: HudStore) => {
    stores.push(store);
    return new Proxy({}, { get: () => () => {} });
  },
}));

const dagData: DagData = {
  now: 100,
  dags: [
    { name: "runs/pr-watch", status: "succeeded", runId: "", startedAt: "", finishedAt: "1970-01-01T00:01:00Z", steps: [{ name: "scan", depends: [], status: "succeeded" }], pool: "runs/main" },
    { name: "runs/sweep", status: "not_started", runId: "", startedAt: "", finishedAt: "", steps: [{ name: "scan", depends: [], status: "not_started" }] },
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
  act(() => stores[0].set({ dags: dagData.dags.map((d) => d.name), dagData, pools: dagData.pools, groups: [{ name: "Board", n: 2 }] }));
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
