// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DagData } from "./dags";
import { Dags } from "./Dags";
import type { Dag, Machine } from "./api";

const dag = (name: string): Dag => ({
  name, status: "succeeded", runId: "", startedAt: "1970-01-01T00:09:00Z", finishedAt: "1970-01-01T00:10:00Z", pool: "runs/main",
  steps: [{ name: "scan", depends: [], status: "succeeded", kind: null }],
});
const state = (id: string, name: string) => ({ id, name, initial: false, final: false });
const board: Machine = {
  states: [state("backlog", "Backlog"), state("ready", "Ready"), state("review", "Review")],
  transitions: [{ source: "backlog", target: "ready", event: "task_ready" }, { source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
  dagActors: ["runs/pr-watch", "runs/sweeper"],
  launches: { "runs/triage": { skill: "triaging", flow: "" } },
};
const data: DagData = {
  now: 3600,
  dags: [dag("runs/pr-watch"), dag("runs/sweeper"), dag("runs/triage"), dag("runs/cued")],
  domains: [{ name: "Board", dags: ["runs/pr-watch", "runs/sweeper", "runs/triage", "runs/cued"].map((name) => ({ name, runSafe: false })) }],
  pools: [{ name: "runs/main", cap: 2, running: 0, queued: 0 }],
  cues: [{ dag: "runs/pr-watch", event: "task_ready", state: "ready", on: "a push to main" }, { dag: "runs/cued", event: "ghost", state: "ready", on: "never" }],
  flows: [{ name: "board", machine: board }],
};

let host: HTMLDivElement, root: Root;
const open = vi.fn();
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel);
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const row = (n: string) => all("#catalog .trow").find((r) => r.querySelector(".nm")!.textContent === n)!;
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const draw = () => act(async () => root.render(<Dags data={data} openPath={open} />));

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  open.mockReset();
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

const ledger = (event: string) => expect.objectContaining({ kind: "fold", event });

describe("a Board tie links to its transition's Ledger", () => {
  it("opens the Ledger from a row's chip without opening the DAG's modal", async () => {
    await draw();
    const chip = row("pr-watch").querySelector<HTMLAnchorElement>("a.tie")!;

    expect(chip.textContent).toBe("⇢ on task_ready");
    await click(chip);
    expect(open).toHaveBeenCalledOnce();
    expect(open).toHaveBeenCalledWith([{ kind: "board" }, ledger("task_ready")]);
    expect(q("#kbm")).toBeNull();
  });

  it("links the modal's tie rows, each with an 'open the <EVENT> Ledger' link", async () => {
    await draw();
    await click(row("pr-watch"));
    const rows = all(".dgm .tierow");

    expect(rows.map((t) => t.querySelector(".lgnote")!.textContent)).toEqual(["open the task_ready Ledger ↗", "open the pr_opened Ledger ↗"]);
    await click(rows[1].querySelector(".lgnote")!);
    expect(open).toHaveBeenCalledWith([{ kind: "board" }, ledger("pr_opened")]);
    await click(rows[0].querySelector("a.tie")!);
    expect(open).toHaveBeenLastCalledWith([{ kind: "board" }, ledger("task_ready")]);
  });

  it("leaves a launches or acts tie a plain chip, in the row and in the modal", async () => {
    await draw();
    for (const name of ["triage", "sweeper"]) {
      expect(row(name).querySelector(".tie")).not.toBeNull();
      expect(row(name).querySelector("a")).toBeNull();
      await click(row(name));
      expect(q(".dgm .tierow .tie")).not.toBeNull();
      expect(q(".dgm .tierow a")).toBeNull();
      expect(q(".dgm .lgnote")).toBeNull();
      await act(async () => { document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
    }
    expect(open).not.toHaveBeenCalled();
  });

  it("leaves a tie plain when its event has no Ledger to open", async () => {
    await draw();

    expect(row("cued").querySelector(".tie")).not.toBeNull();
    expect(row("cued").querySelector("a")).toBeNull();
  });
});
