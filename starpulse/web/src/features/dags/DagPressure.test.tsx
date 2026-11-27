// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DagPressure } from "./DagPressure";
import { dagFacts, type DagData } from "./dagsModel";
import type { Dag } from "../../api";

const dag = (name: string): Dag => ({ name, status: "succeeded", runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, startUrl: "", steps: [] });
const data = (over: Partial<DagData> = {}): DagData => ({
  now: 0, dags: [], domains: [], pools: [], cues: [], flows: [], facts: {}, ...over,
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
  it("draws Run-hours as one card whose body scrolls on its own", async () => {
    await draw(data());

    expect([...host.querySelectorAll("section.card h3")].map((h) => h.textContent)).toEqual(["Run-hours"]);
    expect([...host.querySelectorAll("section.card")].map((s) => s.querySelectorAll(":scope > .body").length)).toEqual([1]);
  });

  it("lists the DAGs by run-hours, most first, the longest filling its bar", async () => {
    await draw(data({ facts: { "runs/a": facts(2), "runs/b": facts(8), "runs/c": facts(null) } }));

    const rows = [...card("Run-hours").querySelectorAll<HTMLElement>(".q")];
    expect(rows.map((r) => r.querySelector(".r")!.textContent)).toEqual(["b8h", "a2h"]);
    expect(rows.map((r) => r.querySelector<HTMLElement>(".m i")!.style.width)).toEqual(["100%", "25%"]);
  });

  it("draws the cards with no hours and no data at all, so the view's navigator never changes shape", async () => {
    await draw(null);

    expect(host.querySelectorAll("section.card")).toHaveLength(1);
    expect(card("Run-hours").textContent).toContain("no runs");
  });
});
