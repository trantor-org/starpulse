import { describe, expect, it } from "vitest";
import { FRESH, LABEL_MAX, bigPlace, captions, chartHeight, cpuPercent, dagData, dagFacts, filterRows, order, panes, place, places, refusal, rows, runHours, stepLabels, ties, type DagData } from "./dagsModel";
import type { Dag, DagStep, Machine, RunStatus } from "../../api";

const step = (name: string, depends: string[] = [], status: RunStatus = "succeeded"): DagStep => ({ name, depends, status, kind: null, precondition: null, lock: null, last: [] });
const dag = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, steps: [step("a"), step("b", ["a"])], ...over,
});

const board: Machine = {
  states: [
    { id: "ready", name: "Ready", initial: false, final: false },
    { id: "review", name: "Review", initial: false, final: false },
  ],
  transitions: [{ source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
  launches: { "runs/triage": { skill: "triaging", machine: "triage-flow" } },
  dagActors: ["runs/sweeper"],
};

const data: DagData = {
  now: 1000, facts: {}, cpu: {},
  dags: [
    dag("runs/pr-watch", "succeeded", { finishedAt: "1970-01-01T00:10:00Z", schedule: [], stats: null, rerun: null, startedAt: "1970-01-01T00:09:00Z" }),
    dag("runs/triage", "failed", { steps: [step("scan"), step("fix", ["scan"], "failed")], finishedAt: "1970-01-01T00:12:00Z" }),
    dag("runs/sweeper", "not_started"),
    dag("runs/backup", "queued"),
    dag("runs/deploy", "succeeded", {
      finishedAt: "1970-01-01T00:11:00Z",
      active: [{ runId: "r1", status: "running", startedAt: "1970-01-01T00:15:00Z", step: "b", stepStartedAt: "", steps: { a: "succeeded", b: "running" } }],
    }),
    dag("runs/lost", "aborted"),
    dag("runs/stray", "succeeded"),
  ],
  domains: [
    { name: "Board", dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/triage", runSafe: false }, { name: "runs/sweeper", runSafe: false }] },
    { name: "Ops", dags: [{ name: "runs/backup", runSafe: false }, { name: "runs/deploy", runSafe: true }, { name: "runs/lost", runSafe: false }] },
  ],
  pools: [],
  cues: [{ dag: "runs/sweeper", event: "task_ready", state: "ready", on: "a push to main" }],
  flows: [{ name: "board", machine: board }],
};

const byName = (name: string) => rows(data).find((r) => r.d.name === name)!;

describe("a DAG's row", () => {
  it("takes its phase from its status, and from its active run when one is running", () => {
    expect(byName("runs/pr-watch").phase).toBe("ok");
    expect(byName("runs/triage").phase).toBe("failed");
    expect(byName("runs/lost").phase).toBe("failed");
    expect(byName("runs/sweeper").phase).toBe("idle");
    expect(byName("runs/backup").phase).toBe("queued");
    expect(byName("runs/deploy").phase).toBe("running");
  });

  it("lays the active run's step statuses over the DAG's own, and names the step it is in", () => {
    const r = byName("runs/deploy");

    expect(r.steps).toEqual({ a: "succeeded", b: "running" });
    expect(r.step).toBe("b");
    expect(r.startedAt).toBe(15 * 60);
    expect(byName("runs/triage").steps).toEqual({ scan: "succeeded", fix: "failed" });
  });

  it("takes its domain and run-safe flag from the snapshot's domains, and puts a DAG in none under Other", () => {
    expect(byName("runs/pr-watch")).toMatchObject({ domain: "Board", runSafe: true });
    expect(byName("runs/triage")).toMatchObject({ domain: "Board", runSafe: false });
    expect(byName("runs/deploy")).toMatchObject({ domain: "Ops", runSafe: true });
    expect(byName("runs/stray")).toMatchObject({ domain: "Other", runSafe: false });
  });
});

const nested: DagData = {
  ...data,
  domains: [{
    name: "Board",
    dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/triage", runSafe: false }, { name: "runs/sweeper", runSafe: false }],
    processes: [
      { name: "Watch", dags: [{ name: "runs/pr-watch", runSafe: true }] },
      { name: "Triage", dags: [{ name: "runs/triage", runSafe: false }] },
    ],
  }],
};

describe("a DAG's process", () => {
  const r = (n: string) => rows(nested).find((x) => x.d.name === n)!;

  it("comes from the domain's processes, Other when the domain packages processes but omits the DAG, none for a flat domain", () => {
    expect(r("runs/pr-watch").process).toBe("Watch");
    expect(r("runs/triage").process).toBe("Triage");
    expect(r("runs/sweeper").process).toBe("Other");
    expect(r("runs/stray").process).toBeNull();
    expect(byName("runs/pr-watch").process).toBeNull();
  });

  it("is matched by the search", () => {
    expect(filterRows(rows(nested), { q: "triage" }).map((x) => x.d.name).sort()).toEqual(["runs/triage"]);
    expect(filterRows(rows(nested), { q: "watch" }).map((x) => x.d.name)).toEqual(["runs/pr-watch"]);
  });

  it("survives the snapshot's reading by the view", () => {
    const sky = {
      now: 5, dags: data.dags, pools: [], cues: [], flows: {}, runnable: new Set(["runs/pr-watch"]),
      groups: [{ name: "Board", dags: ["runs/pr-watch", "runs/triage"], processes: [{ name: "Watch", dags: ["runs/pr-watch"] }, { name: "Triage", dags: ["runs/triage"] }] }, { name: "Ops", dags: ["runs/backup"] }],
    } as unknown as Parameters<typeof dagData>[0];

    expect(dagData(sky).domains).toEqual([
      { name: "Board", dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/triage", runSafe: false }],
        processes: [{ name: "Watch", dags: [{ name: "runs/pr-watch", runSafe: true }] }, { name: "Triage", dags: [{ name: "runs/triage", runSafe: false }] }] },
      { name: "Ops", dags: [{ name: "runs/backup", runSafe: false }] },
    ]);
  });
});

describe("the catalog's order", () => {
  it("lists each domain's DAGs in snapshot membership order, then Other by name", () => {
    // Board: pr-watch, triage, sweeper; Ops: backup, deploy, lost; Other: stray — not by phase
    const names = rows(data).sort(order).map((r) => r.d.name);

    expect(names).toEqual(["runs/pr-watch", "runs/triage", "runs/sweeper", "runs/backup", "runs/deploy", "runs/lost", "runs/stray"]);
  });

  it("holds a row's place when only its phase changes", () => {
    const before = rows(data).sort(order).map((r) => r.d.name);
    const fired: DagData = {
      ...data,
      dags: data.dags.map((d) => (d.name === "runs/pr-watch" ? dag("runs/pr-watch", "running", {
        finishedAt: "1970-01-01T00:10:00Z", startedAt: "1970-01-01T00:09:00Z",
        active: [{ runId: "r2", status: "running", startedAt: "1970-01-01T00:16:00Z", step: "a", stepStartedAt: "", steps: { a: "running", b: "not_started" } }],
      }) : d)),
    };
    const after = rows(fired).sort(order).map((r) => r.d.name);

    expect(after).toEqual(before);
    expect(rows(fired).find((r) => r.d.name === "runs/pr-watch")!.phase).toBe("running");
  });

  it("orders nested process members by process package then membership, not phase", () => {
    const names = rows(nested).filter((r) => r.domain === "Board").sort(order).map((r) => r.d.name);

    expect(names).toEqual(["runs/pr-watch", "runs/triage", "runs/sweeper"]);
  });
});

describe("a DAG's Board ties", () => {
  it("reads the event that cues it, the transition it writes and the skill it launches", () => {
    expect(ties(data, "runs/sweeper")[0]).toMatchObject({ kind: "cue", ev: "task_ready", text: "on task_ready" });
    expect(ties(data, "runs/pr-watch")).toEqual([
      expect.objectContaining({ kind: "writes", ev: "pr_opened", text: "Review", note: "pr_opened: Ready → Review" }),
    ]);
    expect(ties(data, "runs/triage")).toEqual([
      expect.objectContaining({ kind: "launches", text: "triaging", note: "launches triaging, which runs the triage-flow machine" }),
    ]);
  });

  it("names a Board actor that writes no transition, and none for a DAG that touches the Board nowhere", () => {
    expect(ties({ ...data, cues: [] }, "runs/sweeper")).toEqual([expect.objectContaining({ kind: "acts", text: "Board" })]);
    expect(ties(data, "runs/stray")).toEqual([]);
  });

  it("puts a tie that opens a transition's Ledger before one that does not", () => {
    const both = { ...data, cues: [...data.cues, { dag: "runs/triage", event: "retry", state: "ready", on: "a failed run" }] };

    expect(ties(both, "runs/triage").map((t) => t.kind)).toEqual(["cue", "launches"]);
  });
});

describe("filtering the catalog", () => {
  const all = rows(data);
  const names = (rs: typeof all) => rs.map((r) => r.d.name).sort();

  it("matches the search against a DAG's name, a step's name or its domain", () => {
    expect(names(filterRows(all, { q: "pr-watch" }))).toEqual(["runs/pr-watch"]);
    expect(names(filterRows(all, { q: "FIX" }))).toEqual(["runs/triage"]);
    expect(names(filterRows(all, { q: "ops" }))).toEqual(["runs/backup", "runs/deploy", "runs/lost"]);
    expect(filterRows(all, { q: "  " })).toHaveLength(all.length);
  });

  it("narrows by Domain and the search together", () => {
    expect(names(filterRows(all, { dom: "Ops" }))).toEqual(["runs/backup", "runs/deploy", "runs/lost"]);
    expect(names(filterRows(all, { dom: "Board", q: "sweeper" }))).toEqual(["runs/sweeper"]);
  });
});

describe("a DAG's steps as a constellation", () => {
  it("puts a step one column right of the deepest step it depends on, and fits the whole in the width", () => {
    const steps = [step("a"), step("b", ["a"]), step("c", ["a"]), step("d", ["b", "c"])];
    const p = place(steps, 220, 20, 7, 3, 5.5, 34, 7);

    expect(p.cols).toBe(3);
    expect(p.at.a.x).toBeLessThan(p.at.b.x);
    expect(p.at.b.x).toBe(p.at.c.x);
    expect(p.at.c.x).toBeLessThan(p.at.d.x);
    expect(p.at.b.y).not.toBe(p.at.c.y);
    expect(p.span).toBeLessThanOrEqual(220);
  });
});

describe("the modal's step chart", () => {
  const PX150 = 6.1 * 1.5;
  /** Every pair of names that sit on one line of the chart: a name's width is `PX150` a character, centred on its step. */
  const overprints = (steps: DagStep[], p: ReturnType<typeof place>) => {
    const h = p.tall;
    const line = (n: string) => Math.round(p.at[n].y + (p.up(n) ? -14 : 22));
    const half = (n: string) => (PX150 * n.length) / 2;
    const names = steps.map((s) => s.name);
    return names.flatMap((a, i) => names.slice(i + 1).filter((b) => line(a) === line(b) && Math.abs(p.at[a].x - p.at[b].x) < half(a) + half(b)).map((b) => `${a} / ${b}`))
      .concat(names.filter((n) => line(n) < 0 || line(n) > h));
  };

  it("wraps a chart wider than its room onto rows below, every step inside the room and no two names overprinting", () => {
    const chain = Array.from({ length: 12 }, (_, i) => step(`stage-${i}`, i ? [`stage-${i - 1}`] : []));
    const p = bigPlace(chain, 0, chartHeight(1) - 12, PX150, 600);
    const bands = chain.map((s) => p.band?.[s.name]);

    expect(p.span).toBeLessThanOrEqual(600);
    expect(Math.max(...chain.map((s) => p.at[s.name].x))).toBeLessThan(600);
    expect(p.tops?.length ?? 0).toBeGreaterThan(1);
    expect(bands).toEqual([...bands].sort((a, b) => a - b));
    expect(p.tall).toBeGreaterThan(chartHeight(1) * ((p.tops?.length ?? 1) - 1));
    expect(chain.every((s) => p.at[s.name].y > (p.tops?.[p.band?.[s.name] ?? 0] ?? Infinity))).toBe(true);
    expect(overprints(chain, p)).toEqual([]);
  });

  it("keeps a chart that fits its room on one row", () => {
    const chain = Array.from({ length: 3 }, (_, i) => step(`stage-${i}`, i ? [`stage-${i - 1}`] : []));

    expect(bigPlace(chain, 0, chartHeight(1) - 12, PX150, 600).tops).toEqual([0]);
  });

  it("folds a fan wider than five into sub-columns of five, so a wide fan stays five steps high", () => {
    const fan = Array.from({ length: 12 }, (_, i) => step(`child-${i}`, ["root"]));
    const steps = [step("root"), ...fan];
    const p = bigPlace(steps, 0, chartHeight(5) - 12, PX150);
    const xs = new Set(fan.map((s) => p.at[s.name].x));

    expect(p.wide).toBe(5);
    expect(xs.size).toBe(3);
    expect(p.cols).toBe(2);
    expect(p.at.root.x).toBeLessThan(Math.min(...xs));
    expect(overprints(steps, p)).toEqual([]);
  });

  it("spaces adjacent single-step columns so their names at 150% text never overprint, alternating them above and below when they must share a line", () => {
    const chain = ["fetch", "scan", "classify-the-changes", "fix", "open-pull-request", "watch", "merge"];
    const steps = chain.map((n, i) => step(n, i ? [chain[i - 1]] : []));
    const tight = bigPlace(steps, 0, chartHeight(1) - 12, PX150), wide = bigPlace(steps, 1400, chartHeight(1) - 12, PX150);

    expect(tight.wide).toBe(1);
    expect(overprints(steps, tight)).toEqual([]);
    expect(overprints(steps, wide)).toEqual([]);
    expect(steps.some((s) => tight.up(s.name))).toBe(true);
    expect(wide.span).toBeLessThanOrEqual(1400);
    expect(tight.span).toBeLessThan(wide.span);
  });

  it("keeps names beside a stacked column clear of it", () => {
    const steps = [step("a"), step("left-branch", ["a"]), step("right-branch", ["a"]), step("join-them-up", ["left-branch", "right-branch"]), step("ship", ["join-them-up"])];
    const p = bigPlace(steps, 0, chartHeight(2) - 12, PX150);

    expect(overprints(steps, p)).toEqual([]);
  });

  /** A GitHub workflow as the adapter flattens it: each job a step, then each of its steps named `<job> / <step>` in a chain. */
  const workflow = (jobs: string[], each: string[]) => jobs.flatMap((job) => [step(job), ...each.map((s, i) => step(`${job} / ${s}`, [i ? `${job} / ${each[i - 1]}` : job]))]);
  const JOBS = ["Build the release directory", "Switch current to the release directory", "Apply merged changes through Dagu", "Page on two consecutive failed applies"];
  const EACH = ["Set up job", "Run actions/checkout@v4", "Post Run actions/checkout@v4", "Complete job"];

  it("names a step by what follows its parent step's name, and cuts a long name to the label cap", () => {
    const long = "x".repeat(LABEL_MAX + 10);
    const labels = stepLabels([...workflow(JOBS.slice(0, 1), EACH), step("orphan / child"), step(long)]);

    expect(labels["Build the release directory"]).toBe("Build the release directory");
    expect(labels["Build the release directory / Set up job"]).toBe("Set up job");
    expect(labels["orphan / child"]).toBe("orphan / child");
    expect(labels[long]).toHaveLength(LABEL_MAX);
    expect(labels[long].endsWith("…")).toBe(true);
  });

  it("spaces a large workflow's columns by its steps' labels, not their full names", () => {
    const steps = workflow(JOBS, EACH);
    const p = bigPlace(steps, 0, chartHeight(4) - 12, PX150);

    // five columns: the jobs (39 characters at most) then four of labels (28 at most) need about 1500px; their full names (68) need about 3000
    expect(p.span).toBeLessThan(1600);
    expect(p.label["Apply merged changes through Dagu / Complete job"]).toBe("Complete job");
  });
});

describe("why Run now is refused", () => {
  const row = (name: string) => rows(data).find((r) => r.d.name === name)!;
  it("names a running or queued DAG, a DAG that is not run-safe and a run being started, and is silent for a run-safe idle DAG", () => {
    expect(refusal(row("runs/deploy"))).toBe("Already running");
    expect(refusal(row("runs/backup"))).toBe("Already queued");
    expect(refusal(row("runs/triage"))).toMatch(/^Not run-safe/);
    expect(refusal(row("runs/pr-watch"), true)).toBe("Starting…");
    expect(refusal(row("runs/pr-watch"))).toBeNull();
  });
});

describe("the page's snapshot as the DAGs view reads it", () => {
  it("carries the DAGs, their domains with the run-safe flag, the pools, the cues and each machine", () => {
    const sky = {
      now: 5, dags: data.dags, pools: [{ name: "runs/main", cap: 2, running: 1, queued: 0 }], cues: data.cues,
      groups: [{ name: "Board", dags: ["runs/pr-watch", "runs/triage"] }], runnable: new Set(["runs/pr-watch"]),
      flows: { board: { name: "board", machine: board, agents: [{ id: "T-1" }] } },
    } as unknown as Parameters<typeof dagData>[0];
    const read = dagData(sky);

    expect(read.now).toBe(5);
    expect(read.domains).toEqual([{ name: "Board", dags: [{ name: "runs/pr-watch", runSafe: true }, { name: "runs/triage", runSafe: false }] }]);
    expect(read.flows).toEqual([{ name: "board", machine: board }]);
    expect(read.pools).toEqual(sky.pools);
    expect(read.cues).toBe(data.cues);
  });

  it("reads each DAG's schedule, statistics and declared rerun safety, a never-run DAG's as absent and not zero", () => {
    const stats = { runs: 4, hours: 0.5, medianSeconds: 120, p95Seconds: 600, failureShare: 0.25 };
    const rerun = { key: "pr", repeats: null, step: null };
    const ran = dag("runs/ran", "succeeded", { schedule: ["0 * * * *", "30 6 * * 1"], stats, rerun });
    const never = dag("runs/never", "not_started");
    const sky = { now: 5, dags: [ran, never], pools: [], cues: [], groups: [], runnable: new Set(), flows: {} } as unknown as Parameters<typeof dagData>[0];

    expect(dagData(sky).facts).toEqual({
      "runs/ran": { schedule: "0 * * * *, 30 6 * * 1", ...stats, rerun },
      "runs/never": { schedule: "manual", runs: null, hours: null, medianSeconds: null, p95Seconds: null, failureShare: null, rerun: null },
    });
    expect(dagData({ ...sky, cpu: { dagu: { share: 0.25, cores: 36 } } } as unknown as Parameters<typeof dagData>[0]).cpu).toEqual({ dagu: { share: 0.25, cores: 36 } });
    expect(dagFacts(dag("runs/quiet", "succeeded", { stats: { ...stats, runs: 0, hours: 0, medianSeconds: null, p95Seconds: null, failureShare: null } })).runs).toBe(0);
  });
});

describe("the activity panes", () => {
  const names = (rs: { d: { name: string } }[]) => rs.map((r) => r.d.name);
  it("hold a DAG with a run running or queued in Processing and every other DAG in Idle, disjoint and together the catalog", () => {
    const all = rows(data), p = panes(all);
    expect(names(p.processing)).toEqual(["runs/deploy", "runs/backup"]);
    expect(names(p.idle).filter((n) => names(p.processing).includes(n))).toEqual([]);
    expect([...names(p.processing), ...names(p.idle)].sort()).toEqual(names(all).sort());
  });
  it("orders Processing by when its run began, a queued DAG last, so a DAG that starts joins at the bottom", () => {
    const at = (n: string, s: string) => dag(n, "running", { active: [{ runId: "r", status: "running", startedAt: s, step: "a", stepStartedAt: "", steps: {} }] });
    const d: DagData = { ...data, dags: [at("runs/new", "1970-01-01T00:30:00Z"), dag("runs/q", "queued"), at("runs/old", "1970-01-01T00:20:00Z")], domains: [] };
    expect(names(panes(rows(d)).processing)).toEqual(["runs/old", "runs/new", "runs/q"]);
  });
  it("lead Idle with the latest FRESH finished DAGs, newest first, then the rest in catalog order", () => {
    const done = (i: number) => dag(`runs/d${i}`, "succeeded", { finishedAt: new Date((600 + i) * 1000).toISOString() });
    const d: DagData = { ...data, dags: [...Array.from({ length: 7 }, (_, i) => done(i)), dag("runs/never", "not_started")], domains: [] };
    const p = panes(rows(d));
    expect(FRESH).toBe(5);
    expect(names(p.idle).slice(0, FRESH)).toEqual(["runs/d6", "runs/d5", "runs/d4", "runs/d3", "runs/d2"]);
    expect(names(p.idle).slice(FRESH)).toEqual(["runs/d0", "runs/d1", "runs/never"]);
    expect([...p.fresh].sort()).toEqual(["runs/d2", "runs/d3", "runs/d4", "runs/d5", "runs/d6"]);
  });
  it("moves a DAG to Idle on the next snapshot that no longer has its run active, whatever event was dropped", () => {
    const running = { ...data, dags: [dag("runs/x", "running", { active: [{ runId: "r", status: "running", startedAt: "1970-01-01T00:20:00Z", step: "a", stepStartedAt: "", steps: {} }] })], domains: [] };
    const after = { ...running, dags: [dag("runs/x", "succeeded", { finishedAt: "1970-01-01T00:21:00Z" })] };
    expect(names(panes(rows(running)).processing)).toEqual(["runs/x"]);
    expect(names(panes(rows(after)).processing)).toEqual([]);
    expect(names(panes(rows(after)).idle)).toEqual(["runs/x"]);
  });
  it("captions the first row of a group: Just finished over the bucket, a domain where it changes", () => {
    const p = panes(rows(data));
    expect(captions(p.idle, p.fresh)).toEqual(["Just finished · latest 5", null, "Board", "Ops", "Other"]);
    expect(captions(p.processing, p.fresh)).toEqual(["Ops", null]);
  });
});

describe("the panes' row grid", () => {
  it("puts the Processing row and the Idle row of one index at the same height, in the other column", () => {
    const p = panes(rows(data)), { at } = places(p, false);
    p.processing.forEach((r, i) => expect(at.get(r.d.name)).toMatchObject({ col: 0, hs: 1, slot: i }));
    p.idle.forEach((r, i) => expect(at.get(r.d.name)).toMatchObject({ col: 1, hs: 1, slot: i }));
  });
  it("spends a caption band only on a slot where a row of either pane opens a group", () => {
    const p = panes(rows(data)), { at, bands } = places(p, false);
    const open = (rs: typeof p.processing) => captions(rs, p.fresh).map((c) => c !== null);
    const [op, oi] = [open(p.processing), open(p.idle)];
    const slots = Math.max(p.processing.length, p.idle.length);
    const want = Array.from({ length: slots }, (_, i) => Boolean(op[i] || oi[i]));
    const rowAt = (i: number) => at.get((p.idle[i] ?? p.processing[i]).d.name)!;
    want.forEach((b, i) => expect(rowAt(i).band).toBe(b));
    want.forEach((_, i) => expect(rowAt(i).k).toBe(want.slice(0, i).filter(Boolean).length));
    expect(bands).toBe(want.filter(Boolean).length);
  });
  it("stacks Idle under Processing, and its header with it, at a phone's width", () => {
    const p = panes(rows(data)), { at } = places(p, true);
    expect(at.get(p.idle[0].d.name)).toMatchObject({ col: 0, hs: 2, slot: p.processing.length });
    expect(at.get("idle-head")).toMatchObject({ col: 0, hs: 1, slot: p.processing.length });
  });
});

describe("the run pressure the navigator draws", () => {
  const facts = (hours: number | null) => ({ ...dagFacts(dag("x", "succeeded")), hours });

  it("ranks the DAGs by their seven-day run-hours, most first, and leaves out one with none read or none spent", () => {
    const ranked = runHours({ "runs/a": facts(1.5), "runs/b": facts(12), "runs/c": facts(null), "runs/d": facts(0), "runs/e": facts(1.5) });

    expect(ranked).toEqual([{ name: "runs/b", hours: 12 }, { name: "runs/a", hours: 1.5 }, { name: "runs/e", hours: 1.5 }]);
  });

  it("reads the Runner CPU as one percentage of all the cores, summing the runner units of every instance", () => {
    expect(cpuPercent({ dagu: { cores: 8, share: 0.375 } })).toBeCloseTo(37.5);
    expect(cpuPercent({ a: { cores: 8, share: 0.25 }, b: { cores: 8, share: 0.125 } })).toBeCloseTo(37.5);
  });

  it("reads no CPU when the server served none, never zero", () => {
    expect(cpuPercent({})).toBeNull();
  });
});
