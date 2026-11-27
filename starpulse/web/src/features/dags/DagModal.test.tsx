// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DagData } from "./dagsModel";
import { Dags } from "./Dags";
import type { Dag, DagStep, Machine, RunStatus } from "../../api";

const step = (name: string, depends: string[] = [], status: RunStatus = "succeeded", kind?: string): DagStep => ({ name, depends, status, kind: kind ?? null, precondition: null, lock: null, last: [] });
const dag = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "run-abc", startedAt: "1970-01-01T00:09:00Z", finishedAt: "1970-01-01T00:10:00Z", schedule: [], stats: null, rerun: null, startUrl: "", steps: [step("scan"), step("fix", ["scan"], "succeeded", "agent")], pool: "runs/main", ...over,
});
const board: Machine = {
  states: [{ id: "ready", name: "Ready", initial: false, final: false }, { id: "review", name: "Review", initial: false, final: false }],
  transitions: [{ source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
};
const fan = Array.from({ length: 8 }, (_, i) => step(`check-${i}`, ["clone"]));
const data: DagData = {
  now: 3600, facts: {},
  dags: [
    dag("runs/pr-watch", "succeeded", { startUrl: "http://runner.test/pr-watch" }),
    dag("runs/triage", "failed", { steps: [step("scan"), step("fix", ["scan"], "failed")] }),
    dag("runs/deploy", "succeeded", { runId: "", startUrl: "http://runner.test/deploy", active: [{ runId: "r1", url: "http://runner.test/run/r1", status: "running", startedAt: "1970-01-01T00:55:00Z", step: "fix", stepStartedAt: "", steps: { scan: "succeeded", fix: "running" } }] }),
    dag("runs/never", "not_started", { runId: "", startedAt: "", finishedAt: "", pool: "" }),
    dag("runs/fanout", "succeeded", { steps: [step("clone"), ...fan, step("report", fan.map((s) => s.name))] }),
  ],
  domains: [
    { name: "Board", dags: [{ name: "runs/pr-watch" }, { name: "runs/triage" }, { name: "runs/fanout" }] },
    { name: "Ops", dags: [{ name: "runs/deploy" }, { name: "runs/never" }] },
  ],
  pools: [{ name: "runs/main", cap: 2, running: 1, queued: 0 }],
  cues: [{ dag: "runs/pr-watch", event: "task_ready", state: "ready", on: "a push to main" }],
  flows: [{ name: "board", machine: board }],
};

let host: HTMLDivElement, root: Root;
const draw = async () => { await act(async () => root.render(<Dags data={data} />)); };
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const row = (n: string) => all("#stage .drow").find((r) => r.querySelector(".nm")!.textContent === n)!;
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const key = (target: EventTarget, k: string) => act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); });
const cells = () => Object.fromEntries(all(".dgm table tr").map((tr) => [tr.children[0].textContent, tr.children[1].textContent]));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  // The view ticks its clock each second; a frozen interval keeps a slow run from aging the fixture's elapsed times.
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();

  vi.useRealTimers();
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
    expect(chart.querySelectorAll("path.link.hot")).toHaveLength(1);
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

  it("tabulates this or the last run, when it started, its run id, the pool's queue slots", async () => {
    await draw();
    await click(row("pr-watch"));

    expect(cells()["last run"]).toBe("50m ago · 1m 0s");
    expect(cells().started).toMatch(/\(51m ago\)$/);
    expect(cells().run).toBe("run-abc");
    expect(all(".dgm .slots i").map((i) => i.className)).toEqual(["on", ""]);
    expect(q(".dgm .slots span").textContent).toBe("main: 1 of 2 running");

    await key(document, "Escape");
    await click(row("deploy"));
    expect(cells()["this run"]).toBe("fix · 5m 0s");
    expect(cells().run).toBe("r1");

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

describe("the modal's footer links to the runner", () => {
  const foot = () => all(".dgm .tvfoot a").map((a) => [a.textContent, a.getAttribute("href")]);

  it("has only Run in <runner> for a job that never ran", async () => {
    await act(async () => root.render(<Dags data={{ ...data, dags: data.dags.map((d) => (d.name === "runs/never" ? { ...d, startUrl: "http://runner.test/never" } : d)) }} />));
    await click(row("never"));
    expect(foot()).toEqual([["Run in Runs ↗", "http://runner.test/never"]]);
    expect(all(".dgm .tvfoot button")).toEqual([]);
  });

  it("adds Open run for a job with a run on its runner", async () => {
    await draw();
    await click(row("deploy"));
    expect(foot()).toEqual([["Run in Runs ↗", "http://runner.test/deploy"], ["Open run ↗", "http://runner.test/run/r1"]]);
    expect(all(".dgm .tvfoot a").map((a) => a.getAttribute("target"))).toEqual(["_blank", "_blank"]);
  });

  it("has no footer for a job whose runner has no start page and no run to open", async () => {
    await draw();
    await click(row("never"));
    expect(host.querySelector(".dgm .tvfoot")).toBeNull();
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

  it("does not open from the row's Run in link", async () => {
    await draw();
    await click(row("pr-watch").querySelector("a.runin.edge")!);

    expect(host.querySelector("#kbm")).toBeNull();
  });
});

describe("a DAG modal's step history and rerun safety", () => {
  const withSteps = (name: string, steps: DagStep[], over: Partial<Dag> = {}) => {
    const d = data.dags.find((x) => x.name === name)!;
    return { ...data, dags: data.dags.map((x) => (x === d ? { ...x, steps, ...over } : x)) };
  };
  const drawWith = async (d: DagData, name: string) => { await act(async () => root.render(<Dags data={d} />)); await click(row(name)); };
  const hist = () => all(".dgm .hist li");
  const marks = (li: Element) => [...li.querySelectorAll<HTMLElement>(".runs i")].map((i) => i.className);

  it("draws one line per step, newest outcome last, with an empty slot for a run not yet made", async () => {
    const steps: DagStep[] = [{ ...step("scan"), last: ["failed", "succeeded", "succeeded"] }, { ...step("fix", ["scan"], "succeeded", "agent"), last: [] }];
    await drawWith(withSteps("runs/pr-watch", steps), "pr-watch");

    expect(hist().map((li) => li.querySelector(".nm")!.textContent)).toEqual(["scan", "fix"]);
    expect(marks(hist()[0])).toEqual(["", "", "s-succeeded", "s-succeeded", "s-failed"]);
    expect(marks(hist()[1])).toEqual(["", "", "", "", ""]);
  });

  it("names a job's step by what follows the job's name in the chart and the history, the full name in its tooltip", async () => {
    const steps: DagStep[] = [step("Build the release directory"), step("Build the release directory / Set up job", ["Build the release directory"])];
    await drawWith(withSteps("runs/pr-watch", steps), "pr-watch");

    const star = all(".dgm .chart g.sd")[1];
    expect(star.querySelector("text")!.textContent).toBe("Set up job");
    expect(star.querySelector("title")!.textContent).toMatch(/^Build the release directory \/ Set up job: /);
    expect(hist().map((li) => li.querySelector(".nm")!.textContent)).toEqual(["Build the release directory", "Set up job"]);
    expect(hist()[1].querySelector(".nm")!.getAttribute("title")).toBe("Build the release directory / Set up job");
    expect(hist()[1].classList.contains("sub")).toBe(true);
  });

  it("shows a never-run DAG's history as an empty strip for every step", async () => {
    await draw();
    await click(row("never"));

    expect(hist()).toHaveLength(2);
    expect(hist().every((li) => marks(li).length === 5 && marks(li).every((c) => c === ""))).toBe(true);
  });

  it("states the declared rerun safety in the header, and nothing for an undeclared DAG", async () => {
    const header = () => q(".dgm .tvhead .rerun")?.textContent;
    await drawWith(withSteps("runs/pr-watch", data.dags[0].steps, { rerun: { key: "delivery id", repeats: null, step: null } }), "pr-watch");
    expect(header()).toBe("once per delivery id");
    await key(document, "Escape");
    await drawWith(withSteps("runs/pr-watch", data.dags[0].steps, { rerun: { key: null, repeats: null, step: null } }), "pr-watch");
    expect(header()).toBe("safe to rerun");
    await key(document, "Escape");
    await drawWith(withSteps("runs/pr-watch", data.dags[0].steps, { rerun: { key: null, repeats: "pages again", step: "fix" } }), "pr-watch");
    expect(header()).toBe("repeats on rerun · pages again");
    await key(document, "Escape");
    await drawWith(data, "pr-watch");
    expect(q(".dgm .tvhead .rerun")).toBeNull();
  });

  it("notes a repeating step, a precondition and a lock on the step's line", async () => {
    const steps = [{ ...step("scan"), precondition: "$CI == 1", lock: "deploy" }, step("fix", ["scan"], "succeeded", "agent")];
    await drawWith(withSteps("runs/pr-watch", steps, { rerun: { key: null, repeats: "pages again", step: "fix" } }), "pr-watch");

    expect(hist()[0].querySelector(".note")!.textContent).toBe("when $CI == 1 · lock deploy");
    expect(hist()[1].querySelector(".note")!.textContent).toBe("repeats · pages again");
  });

  it("widens the modal with its graph: a long chain's modal is wider than a two-step DAG's", async () => {
    const width = () => parseInt(q<HTMLElement>(".modal.dgm").style.getPropertyValue("--dgw"), 10);
    const chain = Array.from({ length: 9 }, (_, i) => step(`stage-${i}`, i ? [`stage-${i - 1}`] : []));
    await drawWith(withSteps("runs/fanout", chain), "fanout");
    const big = width();
    await key(document, "Escape");
    await click(row("never"));
    const small = width();

    expect(small).toBeGreaterThan(0);
    expect(big).toBeGreaterThan(small);
  });

  it("wraps a chain wider than the viewport's modal onto rows below, its chart no wider than the modal and its links into a new row dropping to it", async () => {
    const was = innerWidth;
    Object.defineProperty(window, "innerWidth", { value: 800, configurable: true });
    const chain = Array.from({ length: 24 }, (_, i) => step(`stage-${i}`, i ? [`stage-${i - 1}`] : []));
    await drawWith(withSteps("runs/fanout", chain), "fanout");
    const chart = q("svg.dstrip.big");
    const ys = new Set([...chart.querySelectorAll("text")].map((t) => t.getAttribute("y")));
    Object.defineProperty(window, "innerWidth", { value: was, configurable: true });

    expect(Number(chart.getAttribute("width"))).toBeLessThanOrEqual(800 - 28);
    expect(ys.size).toBeGreaterThan(1);
    expect([...chart.querySelectorAll("path.link")].some((l) => l.getAttribute("d")!.includes("V"))).toBe(true);
  });
});
