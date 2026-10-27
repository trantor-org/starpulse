// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DagData } from "./dagsModel";
import { lastLine } from "./DagParts";
import { Dags } from "./Dags";
import { rows } from "./dagsModel";
import css from "../../style.css?raw";
import type { Dag, DagStep, Machine, RunStatus } from "../../api";
import { DAG_COLOR } from "../../render/draw";
import { applyDelta } from "../../api/stream";

// every row draws one Strip, so the Strips drawn say which rows rendered
const drawn = vi.hoisted(() => ({ names: [] as string[] }));
vi.mock("./DagParts", async (orig) => {
  const m = await orig<typeof import("./DagParts")>();
  return { ...m, Strip: (p: Parameters<typeof m.Strip>[0]) => (drawn.names.push(p.r.d.name), m.Strip(p)) };
});

const step = (name: string, depends: string[] = [], status: RunStatus = "succeeded"): DagStep => ({ name, depends, status, kind: null, precondition: null, lock: null, last: [] });
const dag = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "", startedAt: "1970-01-01T00:09:00Z", finishedAt: "1970-01-01T00:10:00Z", schedule: [], stats: null, rerun: null, steps: [step("scan"), step("fix", ["scan"])], pool: "runs/main", ...over,
});
const board: Machine = {
  states: [{ id: "ready", name: "Ready", initial: false, final: false }, { id: "review", name: "Review", initial: false, final: false }],
  transitions: [{ source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
};
const data: DagData = {
  now: 3600, facts: {}, cpu: {},
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

let host: HTMLDivElement, root: Root, slot: HTMLDivElement;
const post = vi.fn();
const draw = async (d: DagData | null = data) => { await act(async () => root.render(<Dags data={d} post={post} filterSlot={slot} />)); };
// the navigator's filter slot sits outside the view
const filterBox = () => slot.querySelector<HTMLInputElement>("#dgq")!;
const q = <T extends Element>(sel: string) => host.querySelector<T>(sel)!;
const all = (sel: string) => [...host.querySelectorAll<HTMLElement>(sel)];
const names = () => all("#stage .drow .nm").map((e) => e.textContent);
const paneOf = (pane: string) => all(`.drow[data-pane=${pane}] .nm`).map((e) => e.textContent);
const rowOf = (n: string) => all("#stage .drow").find((r) => r.querySelector(".nm")!.textContent === n)!;
const setText = (box: HTMLInputElement, v: string) => act(() => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(box, v);
  box.dispatchEvent(new Event("input", { bubbles: true }));
});
const click = (el: Element) => act(async () => { (el as HTMLElement).click(); });
const chip = (label: string) => all(".fchip").find((c) => c.textContent!.startsWith(label))!;

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  post.mockReset();
  // The view ticks its clock each second; a frozen interval keeps a slow run from aging the fixture's elapsed times.
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"] });
  localStorage.clear();
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  host = document.body.appendChild(document.createElement("div"));
  slot = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  slot.remove();
  vi.unstubAllGlobals();

  vi.useRealTimers();
});

describe("the DAGs view's panes", () => {
  it("holds exactly the DAGs with a run in flight in Processing, and the rest in Idle: disjoint, and together the catalog", async () => {
    await draw();

    expect(paneOf("processing")).toEqual(["deploy"]);
    expect(paneOf("idle").sort()).toEqual(["never", "pr-watch", "triage"]);
    expect(names().sort()).toEqual(["deploy", "never", "pr-watch", "triage"]);
    expect(all(".phead").map((h) => h.querySelector(".pt")!.textContent! + h.querySelector(".c")!.textContent)).toEqual(["Processing1", "Idle3"]);
  });

  it("puts a queued DAG last in Processing, below the one that began first", async () => {
    const queued = dag("runs/waiting", "queued");
    await draw({ ...data, dags: [...data.dags, queued], domains: [{ name: "Ops", dags: [...data.domains[1].dags, { name: queued.name, runSafe: false }] }, data.domains[0]] });

    expect(paneOf("processing")).toEqual(["deploy", "waiting"]);
  });

  it("moves a DAG whose end event was dropped to Idle on the next snapshot, and says so when Processing empties", async () => {
    await draw();
    expect(paneOf("processing")).toEqual(["deploy"]);

    await draw({ ...data, dags: data.dags.map((d) => (d.name === "runs/deploy" ? { ...d, active: [] } : d)) });

    expect(paneOf("processing")).toEqual([]);
    expect(paneOf("idle")).toContain("deploy");
    expect(q(".phint").textContent).toBe("Nothing is running");
  });

  it("gives a Processing row and the Idle row of its slot one header count and one slot, so they share a top", async () => {
    await draw();
    const place = (n: string) => ["--hs", "--s", "--k", "--b"].map((k) => rowOf(n).style.getPropertyValue(k));

    expect(place("deploy")).toEqual(place("pr-watch"));
    expect(css).toMatch(/#dg :is\(\.drow, \.phead, \.phint\) \{[^}]*left: calc\(var\(--c\) \* \(var\(--wp\) \+ var\(--gap\)\)\)[^}]*transform: translateY\(calc\(var\(--hs\) \* var\(--H\) \+ var\(--s\) \* var\(--R\) \+ var\(--k\) \* var\(--C\)\)\)/);
  });

  it("captions Just finished over the latest finished DAGs of Idle, and a domain where the domain changes", async () => {
    await draw({ ...data, dags: data.dags.map((d) => (d.name === "runs/never" ? { ...d, startedAt: "", finishedAt: "" } : d)) });

    expect(all(".drow[data-pane=idle] .cap").map((c) => c.textContent)).toEqual(["Just finished · latest 5", "Ops"]);
    expect(all(".drow[data-pane=processing] .cap").map((c) => c.textContent)).toEqual(["Ops"]);
  });

  it("draws the first snapshot where it lies, and glides a DAG that changes pane, finished down to Idle or starting down to Processing, for as long as the glide lasts", async () => {
    await draw();
    expect(all("[data-glide]")).toHaveLength(0);

    await draw({ ...data, dags: data.dags.map((d) => (d.name === "runs/deploy" ? { ...d, active: [] } : d.name === "runs/never" ? { ...d, status: "running" as const } : d)) });
    expect(rowOf("deploy").dataset.glide).toBe("finish");
    expect(rowOf("never").dataset.glide).toBe("start");
    expect(all("[data-glide]")).toHaveLength(2);

    await act(async () => { vi.advanceTimersByTime(800); });
    expect(all("[data-glide]")).toHaveLength(0);
  });

  it("moves rows with a transition, and with none under reduced motion", () => {
    expect(css).toMatch(/#dg :is\(\.drow, \.phead, \.phint\) \{[^}]*transition: transform \.42s[^}]*left \.42s[^}]*width \.42s/);
    expect(css).toMatch(/#dg \.drow\[data-glide\] \{[^}]*transition-duration: \.64s/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{ #dg :is\(\.drow, \.phead, \.phint\) \{ transition: none; \} \}/);
  });
});

describe("the DAGs view's rows", () => {
  it("draw a DAG with its dot, name, step strip, last run and first tie", async () => {
    await draw();

    expect(names().sort()).toEqual(["deploy", "never", "pr-watch", "triage"]);
    const row = rowOf("pr-watch");
    expect(row.querySelector("i.orb.o-ok")).not.toBeNull();
    // each step as the Star Map's DAG bodies draw it (renderer drawStars): a dark disc ringed in its status colour round a core dot
    const steps = [...row.querySelectorAll("svg.dstrip g.step")];
    expect(steps).toHaveLength(2);
    for (const g of steps) {
      const ring = g.querySelector("circle.ring")!, core = g.querySelector("circle.core")!;
      expect(Number(core.getAttribute("r"))).toBeCloseTo(Number(ring.getAttribute("r")) * 0.34);
      expect(["0.85", "0.45"]).toContain(ring.getAttribute("stroke-opacity"));
    }
    // and joined, as there, by a dashed curve shaded from one step's colour to the next
    const link = row.querySelector("svg.dstrip path.link")!;
    expect(link.getAttribute("d")).toMatch(/^M[\d.]+ [\d.]+C/);
    expect(link.getAttribute("stroke-dasharray")).toBe("1.8 4.2");
    expect(link.getAttribute("stroke")).toMatch(/^url\(#/);
    expect(row.querySelector("i.orb.o-ok circle.ring")!.getAttribute("stroke")).toBe(DAG_COLOR.succeeded);
    expect(row.querySelector(".sub")!.textContent).toBe("manual · pool main");
    expect([...row.querySelectorAll(".last, .num")].map((c) => c.textContent)).toEqual(["succeeded 50m ago", "—", "—"]);
    expect(row.querySelector(".tie")).toBeNull();
    expect(row.querySelector(".pool")).toBeNull();
    expect(q("header .count").textContent).toBe("4 DAGs · 2 domains");
  });

  it("shows a running DAG's progress and elapsed time, and an idle one's last result", async () => {
    await draw();
    const cell = (n: string, c: string) => rowOf(n).querySelector(c)!.textContent;

    expect(cell("deploy", ".last")).toBe("1/2 done · 1 running");
    expect(cell("deploy", ".num")).toBe("5m 0s");
    expect(cell("triage", ".last")).toBe("failed 50m ago");
    expect(cell("never", ".last")).toBe("never run");
  });

  it("open the modal from a click anywhere on the row, the caption band included, and from Enter on a focused row", async () => {
    await draw();
    const open = () => host.querySelector(".dgm");

    await click(rowOf("pr-watch").querySelector(".last")!);
    expect(open()).not.toBeNull();
    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    await draw();
    await click(rowOf("pr-watch").querySelector(".cap")!);
    expect(open()).not.toBeNull();
  });

  it("have no hover state, only a focus ring and the highlight a Recent line sets", () => {
    const rules = css.split("\n").filter((l) => l.includes(".drow") && l.includes(":hover"));
    expect(rules).toEqual([]);
  });

  it("are taller than the old row, whose card was 40px", () => {
    expect(css).toMatch(/#dg \.drow \.body \{[^}]*height: calc\(54px \* var\(--fs\)\)/);
  });

  it("draw no History tab, heatmap, bins or proposed-group fields", async () => {
    await draw();
    const src = Object.entries(import.meta.glob("./*.{ts,tsx}", { query: "?raw", import: "default", eager: true })).filter(([f]) => !f.includes(".test."));

    expect(all("#dg [role=tab], #dg .heat, #dg .bin")).toHaveLength(0);
    expect(q("#dg").textContent).not.toMatch(/History/);
    expect(src.length).toBeGreaterThan(3);
    for (const [f, text] of src) expect(text as string, f).not.toMatch(/propos/i);
  });

  it("says no DAGs were read when the snapshot has none", async () => {
    await draw(null);

    expect(q("header .count").textContent).toBe("no DAGs read");
    expect(host.querySelector("#stage")).toBeNull();
  });
});

describe("the DAGs view's filters", () => {
  it("narrows the rows with the Domain menu, and counts each choice", async () => {
    await draw();
    await click(chip("Domain"));

    expect(all(".menu button").map((b) => b.textContent)).toEqual(["Board2", "Ops2"]);
    await click(all(".menu button").find((b) => b.textContent!.startsWith("Ops"))!);
    expect(names().sort()).toEqual(["deploy", "never"]);
    expect(chip("Domain").textContent).toBe("Domain: Ops ▾");
    expect(q(".shown").textContent).toBe("2 of 4 shown");
    expect(all(".phead").map((h) => h.querySelector(".pt")!.textContent! + h.querySelector(".c")!.textContent)).toEqual(["Processing1", "Idle1"]);

    await click(q(".clear"));
    expect(names()).toHaveLength(4);
  });

  it("has no Status or Last run menu", async () => {
    await draw();

    expect(all(".fchip").map((c) => c.textContent)).toEqual(["Domain ▾"]);
  });

  it("filters by the name, a step or a domain typed in the search, and says when nothing matches", async () => {
    await draw();
    const box = filterBox();

    setText(box, "deploy");
    expect(names()).toEqual(["deploy"]);
    setText(box, "ops");
    expect(names().sort()).toEqual(["deploy", "never"]);
    setText(box, "zzz");
    expect(host.querySelector("#stage")).toBeNull();
    expect(q("#dg > .none").textContent).toContain("No DAG matches");
  });

  it("draws the search in the navigator's slot, not the canvas, and what it holds narrows both panes", async () => {
    await draw();

    expect(host.querySelector("#dgq")).toBeNull();
    expect(slot.querySelector("#dgq")).not.toBeNull();
    expect([paneOf("processing"), paneOf("idle")]).toEqual([["deploy"], ["pr-watch", "triage", "never"]]);
    setText(filterBox(), "ops");
    expect([paneOf("processing"), paneOf("idle")]).toEqual([["deploy"], ["never"]]);
    setText(filterBox(), "triage");
    expect([paneOf("processing"), paneOf("idle")]).toEqual([[], ["triage"]]);
  });

  it("draws no search where there is no slot to hold it", async () => {
    await act(async () => root.render(<Dags data={data} post={post} />));

    expect(document.querySelector("#dgq")).toBeNull();
  });

  it("opens on the filters it last had, after a reload", async () => {
    await draw();
    setText(filterBox(), "deploy");
    act(() => root.unmount());
    root = createRoot(host);
    await draw();

    expect(filterBox().value).toBe("deploy");
    expect(names()).toEqual(["deploy"]);
  });
});

describe("Run now", () => {
  it("draws the ▶ edge strip on a run-safe row only", async () => {
    await draw();
    const has = (n: string) => !!all("#stage .drow").find((r) => r.querySelector(".nm")!.textContent === n)!.querySelector("button.play.edge");

    expect(has("pr-watch")).toBe(true);
    expect(has("deploy")).toBe(true);
    expect(has("triage")).toBe(false);
    expect(has("never")).toBe(false);
  });

  it("disables ▶ on a DAG already running, and POSTs /api/run/<instance>/<workflow> from the others", async () => {
    post.mockResolvedValue(new Response(JSON.stringify({ runId: "r9" }), { status: 200 }));
    await draw();
    const play = (n: string) => all("#stage .drow").find((r) => r.querySelector(".nm")!.textContent === n)!.querySelector<HTMLButtonElement>("button.play.edge")!;

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

describe("a row's step strip for a wide fan", () => {
  it("draws a ten-way fan, as apply-on-merge's, with no two step stars overlapping, and a three-step fan likewise", async () => {
    const fan = (n: number) => Array.from({ length: n }, (_, i) => step(`apply_${i}`, ["classify"]));
    for (const width of [10, 3]) {
      const steps = [step("validate"), step("classify", ["validate"]), ...fan(width), step("verify", fan(width).map((s) => s.name))];
      await draw({ ...data, dags: [dag("runs/apply", "succeeded", { steps })], domains: [{ name: "Ops", dags: [{ name: "runs/apply", runSafe: false }] }] });
      const rings = all("svg.dstrip g.step circle.ring").map((c) => ({ x: +c.getAttribute("cx")!, y: +c.getAttribute("cy")!, r: +c.getAttribute("r")! }));
      expect(rings).toHaveLength(steps.length);
      for (const [i, a] of rings.entries()) for (const b of rings.slice(i + 1)) expect(Math.hypot(a.x - b.x, a.y - b.y), `${width}-wide fan`).toBeGreaterThanOrEqual(a.r + b.r + 1);
    }
  });
});

describe("a DAGs delta", () => {
  it("re-renders only the rows of the DAGs it changed, and the rows whose slot moved", async () => {
    const wire = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T; // a delta arrives as freshly parsed JSON
    const snap = { dags: data.dags, pools: data.pools } as unknown as Parameters<typeof applyDelta>[0];
    // never starts after deploy did, so it joins the bottom of Processing and no other row changes slot
    const next = applyDelta(snap, { kind: "dags", dags: wire(data.dags.map((d) => (d.name === "runs/never" ? { ...d, status: "running" as const, startedAt: "1970-01-01T00:58:00Z" } : d))), pools: wire(data.pools), error: null });
    await draw();
    drawn.names.length = 0;

    await draw({ ...data, dags: next.dags, pools: next.pools ?? data.pools });

    expect(drawn.names).toEqual(["runs/never"]);
    expect(q(".drow[data-dag='runs/never']").className).toContain("p-running");
    expect(paneOf("processing")).toEqual(["deploy", "never"]);
  });
});
