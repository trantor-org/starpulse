// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DagData } from "./dags";
import { Dags } from "./Dags";
import type { Dag, DagStep, Machine, RunStatus } from "../../api";

const step = (name: string, depends: string[] = [], status: RunStatus = "succeeded", kind?: string): DagStep => ({ name, depends, status, kind: kind ?? null });
const dag = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "run-abc", startedAt: "1970-01-01T00:09:00Z", finishedAt: "1970-01-01T00:10:00Z", steps: [step("scan"), step("fix", ["scan"], "succeeded", "agent")], pool: "runs/main", ...over,
});
const board: Machine = {
  states: [{ id: "ready", name: "Ready", initial: false, final: false }, { id: "review", name: "Review", initial: false, final: false }],
  transitions: [{ source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
};
const fan = Array.from({ length: 8 }, (_, i) => step(`check-${i}`, ["clone"]));
const data: DagData = {
  now: 3600,
  dags: [
    dag("runs/pr-watch", "succeeded"),
    dag("runs/triage", "failed", { steps: [step("scan"), step("fix", ["scan"], "failed")] }),
    dag("runs/deploy", "succeeded", { runId: "", active: [{ runId: "r1", status: "running", startedAt: "1970-01-01T00:55:00Z", step: "fix", stepStartedAt: "", steps: { scan: "succeeded", fix: "running" } }] }),
    dag("runs/never", "not_started", { runId: "", startedAt: "", finishedAt: "", pool: "" }),
    dag("runs/fanout", "succeeded", { steps: [step("clone"), ...fan, step("report", fan.map((s) => s.name))] }),
  ],
  domains: [
    { name: "Board", dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/triage", runSafe: false }, { name: "runs/fanout", runSafe: true }] },
    { name: "Ops", dags: [{ name: "runs/deploy", runSafe: true }, { name: "runs/never", runSafe: false }] },
  ],
  pools: [{ name: "runs/main", cap: 2, running: 1, queued: 0 }],
  cues: [{ dag: "runs/pr-watch", event: "task_ready", state: "ready", on: "a push to main" }],
  flows: [{ name: "board", machine: board }],
};

let host: HTMLDivElement, root: Root;
const post = vi.fn();
const draw = async () => { await act(async () => root.render(<Dags data={data} post={post} />)); };
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const row = (n: string) => all("#catalog .trow").find((r) => r.querySelector(".nm")!.textContent === n)!;
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const key = (target: EventTarget, k: string) => act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });
const cells = () => Object.fromEntries(all(".dgm table tr").map((tr) => [tr.children[0].textContent, tr.children[1].textContent]));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  post.mockReset();
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("opening a DAG's modal", () => {
  it("opens from a row's click, with the title and its state dot, and from Enter on a focused row", async () => {
    await draw();
    expect(host.querySelector("#kbm")).toBeNull();

    await click(row("pr-watch"));
    expect(q(".dgm h2").textContent).toBe("pr-watch");
    expect(q(".dgm h2 i.orb.o-ok")).not.toBeNull();
    await key(document, "Escape");
    expect(host.querySelector("#kbm")).toBeNull();

    expect(row("deploy").tabIndex).toBe(0);
    await key(row("deploy"), "Enter");
    expect(q(".dgm h2").textContent).toBe("deploy");
  });

  it("states the DAG's name, state, domain and pool beneath the title", async () => {
    await draw();
    await click(row("pr-watch"));
    expect(q(".dgm .tvhead .k").textContent).toBe("runs/pr-watch · healthy · Board · pool main");

    await key(document, "Escape");
    await click(row("never"));
    expect(q(".dgm .tvhead .k").textContent).toBe("runs/never · never run · Ops");
  });

  it("draws the full step chart: every step named, an agent step ringed, the running step burning", async () => {
    await draw();
    await click(row("deploy"));
    const chart = q("svg.dstrip.big");

    expect([...chart.querySelectorAll("text")].map((t) => t.textContent)).toEqual(["scan", "fix"]);
    expect(chart.querySelector("text.hot")!.textContent).toBe("fix");
    expect(chart.querySelectorAll("circle.halo")).toHaveLength(1);
    await key(document, "Escape");
    await click(row("pr-watch"));
    expect(q("svg.dstrip.big").querySelectorAll('circle[stroke="var(--agent)"]')).toHaveLength(1);
  });

  it("folds a wide fan into sub-columns and names all its steps", async () => {
    await draw();
    await click(row("fanout"));
    const chart = q("svg.dstrip.big");
    const xs = new Set([...chart.querySelectorAll("text")].filter((t) => t.textContent!.startsWith("check-")).map((t) => t.getAttribute("x")));

    expect(chart.querySelectorAll("text")).toHaveLength(10);
    expect(xs.size).toBe(2);
  });

  it("tabulates this or the last run, when it started, its run id, the pool's queue slots and Run now", async () => {
    await draw();
    await click(row("pr-watch"));

    expect(cells()["last run"]).toBe("50m ago · 1m 0s");
    expect(cells().started).toMatch(/\(51m ago\)$/);
    expect(cells().run).toBe("run-abc");
    expect(all(".dgm .slots i").map((i) => i.className)).toEqual(["on", ""]);
    expect(q(".dgm .slots span").textContent).toBe("main: 1 of 2 running");
    expect(cells()["run now"]).toBe("run-safe: StarPulse may start it");

    await key(document, "Escape");
    await click(row("deploy"));
    expect(cells()["this run"]).toBe("fix · 5m 0s");
    expect(cells().run).toBe("r1");
    expect(cells()["run now"]).toBe("Already running");

    await key(document, "Escape");
    await click(row("never"));
    expect(cells()["last run"]).toBe("never run");
    expect(cells().started).toBe("—");
    expect(cells().queue).toBe("no pool");
  });

  it("lists every Board tie with its note, and says so when a DAG has none", async () => {
    await draw();
    await click(row("pr-watch"));
    const ties = all(".dgm .tierow").map((t) => [t.querySelector(".tie")!.textContent, t.querySelector(".k")!.textContent]);

    expect(ties).toEqual([["⇢ on task_ready", "a push to main; the task lands in Ready"], ["⇢ writes Review", "pr_opened: Ready → Review"]]);
    await key(document, "Escape");
    await click(row("triage"));
    expect(q(".dgm .sec:last-of-type").textContent).toContain("No Board tie");
  });
});

describe("Run now in the modal's footer", () => {
  it("POSTs /api/run/<instance>/<workflow> for a run-safe DAG", async () => {
    post.mockResolvedValue(new Response(JSON.stringify({ runId: "r9" }), { status: 200 }));
    await draw();
    await click(row("pr-watch"));
    const go = q<HTMLButtonElement>(".dgm .tvfoot .startbtn");

    expect(go.textContent).toBe("▶ Run now");
    expect(go.disabled).toBe(false);
    await click(go);
    expect(post).toHaveBeenCalledWith("/api/run/runs/pr-watch", { method: "POST" });
    expect(host.querySelector(".dgm .editrefusal")).toBeNull();
  });

  it("is disabled with its reason on a running DAG and on one that is not run-safe", async () => {
    await draw();
    await click(row("deploy"));
    expect(q<HTMLButtonElement>(".dgm .tvfoot .startbtn").disabled).toBe(true);
    expect(q(".dgm .tvfoot .startbtn").getAttribute("title")).toBe("Already running");

    await key(document, "Escape");
    await click(row("triage"));
    expect(q<HTMLButtonElement>(".dgm .tvfoot .startbtn").disabled).toBe(true);
    expect(cells()["run now"]).toMatch(/^Not run-safe/);
    await click(q(".dgm .tvfoot .startbtn"));
    expect(post).not.toHaveBeenCalled();
  });

  it("shows a refusal in the modal's refusal box, and clears it on the next open", async () => {
    post.mockResolvedValue(new Response(JSON.stringify({ error: "pool runs/main is full" }), { status: 409 }));
    await draw();
    await click(row("pr-watch"));
    await click(q(".dgm .tvfoot .startbtn"));

    expect(q(".dgm .editrefusal").textContent).toBe("Run refused. pool runs/main is full");
    await key(document, "Escape");
    await click(row("pr-watch"));
    expect(host.querySelector(".dgm .editrefusal")).toBeNull();
  });
});

describe("closing the modal", () => {
  it("closes on Esc and on a click on the scrim, not on a click inside it", async () => {
    await draw();
    await click(row("pr-watch"));
    await click(q(".dgm"));
    expect(host.querySelector("#kbm")).not.toBeNull();

    await key(document, "Escape");
    expect(host.querySelector("#kbm")).toBeNull();
    await click(row("pr-watch"));
    await click(q("#kbm"));
    expect(host.querySelector("#kbm")).toBeNull();
  });

  it("does not open from the ▶ strip's click", async () => {
    post.mockResolvedValue(new Response(JSON.stringify({ runId: "r9" }), { status: 200 }));
    await draw();
    await click(row("pr-watch").querySelector("button.play.edge")!);

    expect(host.querySelector("#kbm")).toBeNull();
  });
});
