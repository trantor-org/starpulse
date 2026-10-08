// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DagData } from "./dags";
import { lastLine } from "./DagParts";
import { DagLegend, Dags } from "./Dags";
import { rows } from "./dags";
import type { Dag, DagStep, Machine, RunStatus } from "../../api";

const step = (name: string, depends: string[] = [], status: RunStatus = "succeeded"): DagStep => ({ name, depends, status, kind: null });
const dag = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "", startedAt: "1970-01-01T00:09:00Z", finishedAt: "1970-01-01T00:10:00Z", steps: [step("scan"), step("fix", ["scan"])], pool: "runs/main", ...over,
});
const board: Machine = {
  states: [{ id: "ready", name: "Ready", initial: false, final: false }, { id: "review", name: "Review", initial: false, final: false }],
  transitions: [{ source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
};
const data: DagData = {
  now: 3600,
  dags: [
    dag("runs/pr-watch", "succeeded"),
    dag("runs/triage", "failed", { steps: [step("scan"), step("fix", ["scan"], "failed")] }),
    dag("runs/deploy", "succeeded", { active: [{ runId: "r1", status: "running", startedAt: "1970-01-01T00:55:00Z", step: "fix", stepStartedAt: "", steps: { scan: "succeeded", fix: "running" } }] }),
    dag("runs/never", "not_started"),
  ],
  domains: [
    { name: "Board", dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/triage", runSafe: false }] },
    { name: "Ops", dags: [{ name: "runs/deploy", runSafe: true }, { name: "runs/never", runSafe: false }] },
  ],
  pools: [{ name: "runs/main", cap: 2, running: 1, queued: 0 }],
  cues: [],
  flows: [{ name: "board", machine: board }],
};

let host: HTMLDivElement, root: Root;
const post = vi.fn();
const draw = async (d: DagData | null = data) => { await act(async () => root.render(<Dags data={d} post={post} />)); };
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const names = () => all("#catalog .trow .nm").map((e) => e.textContent);
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const chip = (label: string) => all(".fchip").find((c) => c.textContent!.startsWith(label))!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  post.mockReset();
  localStorage.clear();
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the DAGs view's catalog", () => {
  it("draws a fold per domain with its census, and a row per DAG with its dot, name, step strip, last run, pool and first tie", async () => {
    await draw();

    expect(all(".bucket .bh .bn").map((e) => e.textContent!.replace(/\d+$/, "").trim().split(" ")[0])).toEqual(["Board", "Ops"]);
    expect(q(".bucket:last-child .bh .census").textContent).toBe("11");
    expect(names()).toEqual(["triage", "pr-watch", "deploy", "never"]);
    const row = all("#catalog .trow").find((r) => r.querySelector(".nm")!.textContent === "pr-watch")!;
    expect(row.querySelector("i.orb.o-ok")).not.toBeNull();
    expect(row.querySelectorAll("svg.dstrip circle")).toHaveLength(2);
    expect(row.querySelector(".last")!.textContent).toBe("50m ago · 1m 0s");
    expect(row.querySelector(".pool")!.textContent).toBe("main 1/2");
    expect(row.querySelector(".tie")!.textContent).toBe("⇢ Review");
    expect(q("header .count").textContent).toBe("4 DAGs · 2 domains");
  });

  it("shows a running DAG's step and a failed one's failing step in its last-run cell", async () => {
    await draw();
    const last = (n: string) => all("#catalog .trow").find((r) => r.querySelector(".nm")!.textContent === n)!.querySelector(".last")!.textContent;

    expect(last("deploy")).toBe("fix · 5m 0s");
    expect(last("triage")).toBe("failed at fix · 50m ago");
    expect(last("never")).toBe("never run");
  });

  it("folds a domain's rows away and back from its header", async () => {
    await draw();
    await click(q(".bucket .bh"));

    expect(names()).toEqual(["deploy", "never"]);
    await click(q(".bucket .bh"));
    expect(names()).toHaveLength(4);
  });

  it("says no DAGs were read when the snapshot has none", async () => {
    await draw(null);

    expect(q("header .count").textContent).toBe("no DAGs read");
    expect(host.querySelector("#catalog")).toBeNull();
  });
});

describe("the DAGs view's filters", () => {
  it("narrows the rows with the Status menu and the Domain menu, and counts each choice", async () => {
    await draw();
    await click(chip("Status"));

    expect(all(".menu button").map((b) => b.textContent)).toEqual(["Running1", "Failing1", "Not run1", "Healthy1"]);
    await click(all(".menu button").find((b) => b.textContent!.startsWith("Failing"))!);
    expect(names()).toEqual(["triage"]);
    expect(chip("Status").textContent).toBe("Status: Failing ▾");
    expect(q(".shown").textContent).toBe("1 of 4 shown");

    await click(chip("Domain"));
    await click(all(".menu button").find((b) => b.textContent!.startsWith("Ops"))!);
    expect(host.querySelector("#catalog")).toBeNull();
    expect(q("#dg > .none").textContent).toContain("No DAG matches");

    await click(q(".clear"));
    expect(names()).toHaveLength(4);
  });

  it("filters by the name, a step or a domain typed in the search", async () => {
    await draw();
    const box = q<HTMLInputElement>('.filters input');
    const type = (v: string) => act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(box, v);
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });

    type("deploy");
    expect(names()).toEqual(["deploy"]);
    type("ops");
    expect(names()).toEqual(["deploy", "never"]);
  });

  it("opens on the filters it last had, after a reload", async () => {
    await draw();
    const box = q<HTMLInputElement>('.filters input');
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(box, "deploy");
      box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => root.unmount());
    root = createRoot(host);
    await draw();

    expect(q<HTMLInputElement>('.filters input').value).toBe("deploy");
    expect(names()).toEqual(["deploy"]);
  });

  it("hides a DAG last run before the Last run window, keeps one running, and counts each window", async () => {
    await draw({ ...data, now: 40 * 86400 });
    await click(chip("Last run"));

    expect(all(".menu button").map((b) => b.textContent)).toEqual(["Past hour1", "Past day1", "Past week1", "Past month1", "Past year3"]);
    await click(all(".menu button").find((b) => b.textContent!.startsWith("Past week"))!);
    expect(names()).toEqual(["deploy"]);
    expect(chip("Last run").textContent).toBe("Last run: Past week ▾");
    expect(q(".shown").textContent).toBe("1 of 4 shown");

    await click(q(".clear"));
    expect(names()).toHaveLength(4);
  });
});

describe("Run now", () => {
  it("draws the ▶ edge strip on a run-safe row only", async () => {
    await draw();
    const has = (n: string) => !!all("#catalog .trow").find((r) => r.querySelector(".nm")!.textContent === n)!.querySelector("button.play.edge");

    expect(has("pr-watch")).toBe(true);
    expect(has("deploy")).toBe(true);
    expect(has("triage")).toBe(false);
    expect(has("never")).toBe(false);
  });

  it("disables ▶ on a DAG already running, and POSTs /api/run/<instance>/<workflow> from the others", async () => {
    post.mockResolvedValue(new Response(JSON.stringify({ runId: "r9" }), { status: 200 }));
    await draw();
    const play = (n: string) => all("#catalog .trow").find((r) => r.querySelector(".nm")!.textContent === n)!.querySelector<HTMLButtonElement>("button.play.edge")!;

    expect(play("deploy").disabled).toBe(true);
    await click(play("pr-watch"));

    expect(post).toHaveBeenCalledWith("/api/run/runs/pr-watch", { method: "POST" });
    expect(q(".dtoast").textContent).toBe("pr-watch: Started run r9.");
  });

  it("shows a refusal's error in the toast", async () => {
    post.mockResolvedValue(new Response(JSON.stringify({ error: "pool runs/main is full" }), { status: 409 }));
    await draw();
    await click(all("button.play.edge")[0]);

    expect(q(".dtoast").textContent).toContain("Not started: pool runs/main is full");
  });
});

describe("the DAGs view's legend", () => {
  it("names the dot states, the steps, an agent step, a Board tie and a run-safe row", () => {
    const html = renderToStaticMarkup(<DagLegend />);

    for (const word of ["running", "healthy", "last run failed", "never run", "steps", "agent step", "Board tie", "run-safe"]) expect(html).toContain(word);
  });
});

describe("a row's last run cell for a run with no recorded time", () => {
  const cell = (d: Dag) => renderToStaticMarkup(<>{lastLine(rows({ ...data, dags: [d] })[0], 3600)}</>).replace(/<[^>]+>/g, "");

  it("names the step of a running DAG with no start time and no duration, rather than an age since the epoch", () => {
    expect(cell(dag("runs/a", "running", { startedAt: "", finishedAt: "" }))).toBe("starting");
  });

  it("leaves out the age and duration of a healthy DAG that has no finish or start time", () => {
    expect(cell(dag("runs/a", "succeeded", { startedAt: "", finishedAt: "" }))).toBe("ran");
    expect(cell(dag("runs/a", "succeeded", { startedAt: "", finishedAt: "1970-01-01T00:55:00Z" }))).toBe("5m ago");
  });
});
