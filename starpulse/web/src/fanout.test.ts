import { describe, expect, it } from "vitest";
import { fanBadge, fanTip, poolRows, RunEvents, stepRings, stepStatus } from "./fanout";
import type { ActiveRun, Dag, DagStep, Pool, RunStatus } from "./types";

const pool = (name: string, cap: number, running: number, queued = 0): Pool => ({ name, cap, running, queued });

describe("the navigator's pool rows", () => {
  it("writes each pool's running count against its cap", () => {
    const [row] = poolRows([pool("dagu/deliver", 32, 5)]);

    expect(row).toMatchObject({ label: "deliver", count: "5/32", queued: "", full: false, busy: true });
    expect(row.pct).toBeCloseTo(15.625);
  });

  it("adds the queued runs as +q and nothing when none wait", () => {
    const rows = poolRows([pool("dagu/deliver", 32, 32, 6), pool("dagu/default", 2, 1)]);

    expect(rows.map((r) => r.queued)).toEqual(["+6", ""]);
  });

  it("is full, and so red, once the pool runs its cap, and only then", () => {
    const rows = poolRows([pool("dagu/deliver", 32, 32), pool("dagu/models", 1, 1), pool("dagu/gpu-1", 1, 0), pool("dagu/default", 2, 1)]);

    expect(rows.map((r) => r.full)).toEqual([true, true, false, false]);
    expect(rows.map((r) => r.pct)).toEqual([100, 100, 0, 50]);
  });

  it("is idle, with no colour, while nothing runs", () => {
    expect(poolRows([pool("dagu/models", 1, 0)])[0]).toMatchObject({ busy: false, full: false, count: "0/1" });
  });

  it("draws a pool with no cap as empty rather than dividing by zero", () => {
    expect(poolRows([pool("dagu/paused", 0, 0)])[0]).toMatchObject({ pct: 0, full: false });
  });

  it("names a pool by its bare name unless another instance runs one by it", () => {
    expect(poolRows([pool("dagu/deliver", 32, 0), pool("other/default", 2, 0)]).map((r) => r.label)).toEqual(["deliver", "default"]);
    expect(poolRows([pool("dagu/default", 2, 0), pool("other/default", 2, 0)]).map((r) => r.label)).toEqual(["dagu/default", "other/default"]);
  });

  it("lists no row when the adapter reports no pools", () => {
    expect(poolRows(undefined)).toEqual([]);
    expect(poolRows([])).toEqual([]);
  });
});

const run = (runId: string, status: RunStatus, step: string, steps: Record<string, RunStatus> = {}): ActiveRun => ({
  runId, status, startedAt: "2026-10-05T16:00:00Z", step, stepStartedAt: "2026-10-05T16:00:05Z", steps,
});
const dag = (active: ActiveRun[], over: Partial<Dag> = {}): Dag => ({
  name: "dagu/deliver", status: "running", runId: "", startedAt: "", finishedAt: "", steps: [], active, ...over,
});
const A = "deliver-agent-task-2787-1", B = "deliver-agent-task-2801-2";

describe("the Recent feed's run lines", () => {
  it("writes nothing for the runs already in flight when the page first reads them", () => {
    const events = new RunEvents();

    events.observe([dag([run(A, "running", "lint")])], 100);

    expect(events.lines).toEqual([]);
  });

  it("writes a started line, naming the task the run id embeds, when a running run appears", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run(A, "running", "refuse")])], 101);

    expect(events.lines).toMatchObject([{ who: "deliver", where: "started · TASK-2787", at: 101, tone: undefined, fresh: true }]);
  });

  it("writes a queued line for a run that appears queued, then a started line when it starts", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run(A, "queued", "")])], 101);
    events.observe([dag([run(A, "running", "refuse")])], 105);

    expect(events.lines.map((l) => l.where)).toEqual(["started · TASK-2787", "queued · TASK-2787"]);
  });

  it("writes the step a run enters, and only when its step changes", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "refuse")])], 100);

    events.observe([dag([run(A, "running", "refuse")])], 101);
    events.observe([dag([run(A, "running", "lint")])], 102);

    expect(events.lines.map((l) => l.where)).toEqual(["lint · TASK-2787"]);
  });

  it("follows each run on its own, so two runs of one DAG at different steps each write their step", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "lint"), run(B, "running", "lint")])], 100);

    events.observe([dag([run(A, "running", "wait_ci"), run(B, "running", "lint")])], 101);
    events.observe([dag([run(A, "running", "wait_ci"), run(B, "running", "commit")])], 102);

    expect(events.lines.map((l) => l.where)).toEqual(["commit · TASK-2801", "wait_ci · TASK-2787"]);
  });

  it("writes a green succeeded line when a run leaves active with every step it reached done", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "ready", { lint: "succeeded", ready: "running" })])], 100);

    events.observe([dag([])], 101);

    expect(events.lines).toMatchObject([{ who: "deliver", where: "succeeded · TASK-2787", tone: "ok", runId: A }]);
  });

  it("writes a red failed line, naming the step, when a run leaves active having failed in it", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "lint", { lint: "running" })])], 100);
    events.observe([dag([run(A, "running", "lint", { lint: "failed" })])], 101);

    events.observe([dag([])], 102);

    expect(events.lines[0]).toMatchObject({ where: "failed at lint · TASK-2787", tone: "failed", runId: A });
  });

  it("takes the outcome of the DAG's own latest run from the DAG when the run is it", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "ready", { ready: "running" })], { runId: A })], 100);

    events.observe([dag([], { runId: A, status: "failed" })], 101);

    expect(events.lines[0]).toMatchObject({ where: "failed · TASK-2787", tone: "failed" });
  });

  it("names a demo run after the demo task its id embeds", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run("deliver-agent-demo-4", "running", "refuse")])], 101);

    expect(events.lines[0].where).toBe("started · DEMO-4");
  });

  it("falls back to the run id when it embeds no task", () => {
    const events = new RunEvents();
    events.observe([dag([])], 100);

    events.observe([dag([run("nightly-20261005", "running", "a")])], 101);

    expect(events.lines[0].where).toBe("started · nightly-20261005");
  });

  it("keeps the newest dozen lines, newest first", () => {
    const events = new RunEvents();
    events.observe([dag([])], 0);

    for (let i = 1; i <= 15; i++) events.observe([dag([run(`deliver-task-${i}`, "running", "a")])], i);

    expect(events.lines).toHaveLength(12);
    expect(events.lines[0].at).toBe(15);
  });

  it("starts afresh after a resync, so a reconnect's runs are not announced as new", () => {
    const events = new RunEvents();
    events.observe([dag([run(A, "running", "lint")])], 100);

    events.resync();
    events.observe([dag([run(A, "running", "lint"), run(B, "running", "refuse")])], 101);

    expect(events.lines).toEqual([]);
  });
});

describe("a DAG glyph's fan-out", () => {
const STEPS = ["refuse", "lint", "push", "wait_ci"];
const run = (id: string, status: RunStatus, step: string, steps: Record<string, RunStatus> = {}): ActiveRun => ({
  runId: id, status, startedAt: "2026-10-05T23:00:00Z", step, stepStartedAt: "2026-10-05T23:01:00Z",
  steps: { ...Object.fromEntries(STEPS.map((s) => [s, "not_started"])), ...steps } as Record<string, RunStatus>,
});
const dag = (active: ActiveRun[], pool = "deliver"): Pick<Dag, "active" | "pool"> => ({ active, pool });
const pools = (running: number, cap = 32, queued = 0): Pool[] => [{ name: "deliver", cap, running, queued }];

describe("the DAG glyph's fan-out badge", () => {
  it("reads this DAG's running runs over its pool's cap", () => {
    const d = dag([run("a", "running", "wait_ci"), run("b", "running", "lint")]);
    expect(fanBadge(d, pools(5))).toEqual({ text: "2/32", full: false });
  });

  it("adds +q for this DAG's queued runs", () => {
    const d = dag([run("a", "running", "lint"), run("b", "queued", ""), run("c", "queued", "")]);
    expect(fanBadge(d, pools(1, 32, 2))).toEqual({ text: "1/32 +2", full: false });
  });

  it("is red once the pool's running runs fill its cap, whichever DAG holds them", () => {
    const d = dag([run("a", "running", "lint")]);
    expect(fanBadge(d, pools(32))).toEqual({ text: "1/32", full: true });
  });

  it("shows a queued-only DAG as 0/cap +q", () => {
    expect(fanBadge(dag([run("a", "queued", "")]), pools(2, 2, 1))).toEqual({ text: "0/2 +1", full: true });
  });

  it("is hidden while the DAG is idle", () => {
    expect(fanBadge(dag([]), pools(0))).toBeNull();
    expect(fanBadge({ pool: "deliver" }, pools(0))).toBeNull();
  });

  it("is hidden when the adapter reports no pool for the DAG", () => {
    const d = dag([run("a", "running", "lint")]);
    expect(fanBadge(d, [])).toBeNull();
    expect(fanBadge(d, undefined)).toBeNull();
    expect(fanBadge(dag([run("a", "running", "lint")], ""), pools(1))).toBeNull();
  });
});

describe("a glyph step's status from the runs in flight", () => {
  it("is the DAG's own status for the step while no run is in flight", () => {
    expect(stepStatus(dag([]), "lint", "succeeded")).toBe("succeeded");
    expect(stepStatus(dag([run("q", "queued", "")]), "lint", "succeeded")).toBe("succeeded");
  });

  it("is running while any run is in the step", () => {
    const d = dag([run("a", "running", "wait_ci", { refuse: "succeeded", lint: "succeeded", push: "succeeded", wait_ci: "running" }),
      run("b", "running", "lint", { refuse: "succeeded", lint: "running" })]);
    expect(stepStatus(d, "wait_ci", "not_started")).toBe("running");
    expect(stepStatus(d, "lint", "not_started")).toBe("running");
  });

  it("is succeeded once a run is past the step and none is in it", () => {
    const d = dag([run("a", "running", "wait_ci", { refuse: "succeeded", lint: "succeeded", push: "succeeded", wait_ci: "running" })]);
    expect(stepStatus(d, "push", "not_started")).toBe("succeeded");
  });

  it("is not_started when runs are in flight and none has reached the step", () => {
    const d = dag([run("a", "running", "lint", { refuse: "succeeded", lint: "running" })]);
    expect(stepStatus(d, "wait_ci", "succeeded")).toBe("not_started");
  });

  it("is failed when a run failed in the step, over a run still in it", () => {
    const d = dag([run("a", "running", "lint", { refuse: "succeeded", lint: "failed" }), run("b", "running", "lint", { refuse: "succeeded", lint: "running" })]);
    expect(stepStatus(d, "lint", "not_started")).toBe("failed");
  });
});

describe("the DAG tooltip's fan-out line", () => {
  it("says how many of the pool's slots the DAG holds and how its runs spread over the steps", () => {
    const d = dag([run("a", "running", "wait_ci"), run("b", "running", "wait_ci"), run("c", "running", "lint"), run("d", "running", "wait_ci"), run("e", "running", "wait_ci")]);
    expect(fanTip(d, pools(5))).toBe('<div class="k">5 of 32 running on queue deliver</div><div class="k">4 at wait_ci · 1 at lint</div>');
  });

  it("adds the queued runs", () => {
    const d = dag([run("a", "running", "lint"), run("b", "queued", ""), run("c", "queued", "")]);
    expect(fanTip(d, pools(1, 32, 2))).toBe('<div class="k">1 of 32 running on queue deliver · 2 queued</div><div class="k">1 at lint</div>');
  });

  it("drops the step spread when only queued runs exist", () => {
    expect(fanTip(dag([run("a", "queued", "")]), pools(2, 2, 1))).toBe('<div class="k">0 of 2 running on queue deliver · 1 queued</div>');
  });

  it("is empty while idle or when the adapter reports no pool", () => {
    expect(fanTip(dag([]), pools(0))).toBe("");
    expect(fanTip(dag([run("a", "running", "lint")]), [])).toBe("");
  });

  it("escapes a step name", () => {
    expect(fanTip(dag([run("a", "running", "<b>")]), pools(1))).toContain("1 at &lt;b&gt;");
  });
});

describe("the rings a DAG's runs raise on its glyph", () => {
  const whole = (active: ActiveRun[], status: RunStatus = "running", runId = "a", steps: Partial<Record<string, RunStatus>> = {}): Dag => ({
    name: "deliver", status, runId, startedAt: "", finishedAt: "", pool: "deliver", active,
    steps: STEPS.map((name): DagStep => ({ name, depends: [], status: steps[name] ?? "not_started" })),
  });

  it("rings, amber, the step a run enters", () => {
    const before = whole([run("a", "running", "lint")]), after = whole([run("a", "running", "push")]);
    expect(stepRings(before, after)).toEqual([{ step: "push", status: "running" }]);
  });

  it("rings the first step of a run that starts, and of a queued run that takes a slot", () => {
    expect(stepRings(whole([]), whole([run("a", "running", "refuse")]))).toEqual([{ step: "refuse", status: "running" }]);
    expect(stepRings(whole([run("a", "queued", "")]), whole([run("a", "running", "refuse")]))).toEqual([{ step: "refuse", status: "running" }]);
  });

  it("rings a step once, however many runs sit in it, and nothing for a run that stays", () => {
    const same = whole([run("a", "running", "lint"), run("b", "running", "lint")]);
    expect(stepRings(same, same)).toEqual([]);
    expect(stepRings(whole([run("a", "running", "refuse"), run("b", "running", "refuse")]), same)).toEqual([{ step: "lint", status: "running" }]);
  });

  it("rings the step a run ended in, green when the DAG's latest run succeeded", () => {
    const before = whole([run("a", "running", "wait_ci")]), after = whole([], "succeeded", "a");
    expect(stepRings(before, after)).toEqual([{ step: "wait_ci", status: "succeeded" }]);
  });

  it("rings, red, the step that failed when the DAG's latest run failed", () => {
    const before = whole([run("a", "running", "lint")]), after = whole([], "failed", "a", { refuse: "succeeded", lint: "failed" });
    expect(stepRings(before, after)).toEqual([{ step: "lint", status: "failed" }]);
  });

  it("rings no outcome for an ended run that is not the DAG's latest, which carries none", () => {
    const before = whole([run("a", "running", "wait_ci"), run("b", "running", "lint")], "running", "b");
    const after = whole([run("b", "running", "lint")], "running", "b");
    expect(stepRings(before, after)).toEqual([]);
  });

  it("rings nothing for a DAG first seen or a run with no step yet", () => {
    expect(stepRings(undefined, whole([run("a", "running", "lint")]))).toEqual([]);
    expect(stepRings(whole([]), whole([run("a", "running", "")]))).toEqual([]);
  });
});
});
