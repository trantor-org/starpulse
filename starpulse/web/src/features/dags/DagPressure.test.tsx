// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DagPressure } from "./DagPressure";
import { dagFacts, type DagData } from "./dagsModel";
import type { Dag } from "../../api";

const dag = (name: string): Dag => ({ name, status: "succeeded", runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [] });
const data = (over: Partial<DagData> = {}): DagData => ({
  now: 0, dags: [], domains: [], pools: [], cpu: {}, cues: [], flows: [], facts: {}, ...over,
});
const facts = (hours: number | null) => ({ ...dagFacts(dag("x")), hours });

let host: HTMLDivElement, root: Root;
const draw = (d: DagData | null) => act(async () => root.render(<DagPressure data={d} />));
const card = (title: string) => [...host.querySelectorAll<HTMLElement>("section.card")].find((s) => s.querySelector("h3")!.textContent === title)!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("the navigator's run pressure cards", () => {
  it("draws Run-hours and Runner CPU in that order, each with a body that scrolls on its own", async () => {
    await draw(data());

    expect([...host.querySelectorAll("section.card h3")].map((h) => h.textContent)).toEqual(["Run-hours", "Runner CPU"]);
    expect([...host.querySelectorAll("section.card")].map((s) => s.querySelectorAll(":scope > .body").length)).toEqual([1, 1]);
  });

  it("draws the Runner CPU as one bar whose fill and figure are the served share of all cores", async () => {
    await draw(data({ cpu: { dagu: { cores: 8, share: 0.375 } } }));

    const cpu = card("Runner CPU");
    expect(cpu.querySelectorAll(".m i")).toHaveLength(1);
    expect(parseFloat(cpu.querySelector<HTMLElement>(".m i")!.style.width)).toBeCloseTo(37.5, 0);
    expect(cpu.querySelector(".r b")!.textContent).toBe("38%");
  });

  it("says no CPU was read when the server served none, with an empty bar", async () => {
    await draw(data());

    expect(card("Runner CPU").textContent).toContain("not read");
    expect(card("Runner CPU").querySelector<HTMLElement>(".m i")!.style.width).toBe("0%");
  });

  it("lists the DAGs by run-hours, most first, the longest filling its bar", async () => {
    await draw(data({ facts: { "runs/a": facts(2), "runs/b": facts(8), "runs/c": facts(null) } }));

    const rows = [...card("Run-hours").querySelectorAll<HTMLElement>(".q")];
    expect(rows.map((r) => r.querySelector(".r")!.textContent)).toEqual(["b8h", "a2h"]);
    expect(rows.map((r) => r.querySelector<HTMLElement>(".m i")!.style.width)).toEqual(["100%", "25%"]);
  });

  it("draws the cards with no hours and no data at all, so the view's navigator never changes shape", async () => {
    await draw(null);

    expect(host.querySelectorAll("section.card")).toHaveLength(2);
    expect(card("Run-hours").textContent).toContain("no runs");
  });
});
