import { describe, expect, it } from "vitest";
import { bigPlace, chartHeight, dagData, filterRows, order, place, RECENCY, refusal, rows, ties, type DagData } from "./dags";
import type { Dag, DagStep, Machine, RunStatus } from "./api";

const step = (name: string, depends: string[] = [], status: RunStatus = "succeeded"): DagStep => ({ name, depends, status, kind: null });
const dag = (name: string, status: RunStatus, over: Partial<Dag> = {}): Dag => ({
  name, status, runId: "", startedAt: "", finishedAt: "", steps: [step("a"), step("b", ["a"])], ...over,
});

const board: Machine = {
  states: [
    { id: "ready", name: "Ready", initial: false, final: false },
    { id: "review", name: "Review", initial: false, final: false },
  ],
  transitions: [{ source: "ready", target: "review", event: "pr_opened" }],
  writers: { pr_opened: [{ actor: "runs/pr-watch", trigger: "schedule" }] },
  launches: { "runs/triage": { skill: "triaging", flow: "triage-flow" } },
  dagActors: ["runs/sweeper"],
};

const data: DagData = {
  now: 1000,
  dags: [
    dag("runs/pr-watch", "succeeded", { finishedAt: "1970-01-01T00:10:00Z", startedAt: "1970-01-01T00:09:00Z" }),
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

describe("the catalog's order", () => {
  it("lists running, queued, failed, never run, then healthy, the newest finish first within a phase", () => {
    const names = rows(data).sort(order).map((r) => r.d.name);

    expect(names).toEqual(["runs/deploy", "runs/backup", "runs/triage", "runs/lost", "runs/sweeper", "runs/pr-watch", "runs/stray"]);
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

  it("keeps a queued DAG under Running, and narrows by Status and Domain together", () => {
    expect(names(filterRows(all, { only: "running" }))).toEqual(["runs/backup", "runs/deploy"]);
    expect(names(filterRows(all, { only: "failed" }))).toEqual(["runs/lost", "runs/triage"]);
    expect(names(filterRows(all, { only: "failed", dom: "Ops" }))).toEqual(["runs/lost"]);
    expect(names(filterRows(all, { dom: "Board", q: "sweeper" }))).toEqual(["runs/sweeper"]);
  });

  it("keeps, within a Last run window, a DAG active now or last run inside it, and drops one last run earlier or never", () => {
    const at = (s: number) => new Date(s * 1000).toISOString();
    const recent = rows({ ...data, now: 10 * 86400, dags: [
      dag("runs/fresh", "succeeded", { startedAt: at(10 * 86400 - 1800), finishedAt: at(10 * 86400 - 1700) }),
      dag("runs/stale", "failed", { startedAt: at(86400), finishedAt: at(86400 + 60) }),
      dag("runs/live", "running", { startedAt: at(86400) }),
      dag("runs/waiting", "queued"),
      dag("runs/never", "not_started"),
    ] });

    expect(names(filterRows(recent, { since: 10 * 86400 - 3600 }))).toEqual(["runs/fresh", "runs/live", "runs/waiting"]);
    expect(names(filterRows(recent, { since: 0 }))).toHaveLength(5);
    expect(RECENCY.map(([l, s]) => [l, s])).toEqual([["Past hour", 3600], ["Past day", 86400], ["Past week", 604800], ["Past month", 2592000], ["Past year", 31536000]]);
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
    const h = chartHeight(p.wide);
    const line = (n: string) => Math.round(p.at[n].y + (p.up(n) ? -14 : 22));
    const half = (n: string) => (PX150 * n.length) / 2;
    const names = steps.map((s) => s.name);
    return names.flatMap((a, i) => names.slice(i + 1).filter((b) => line(a) === line(b) && Math.abs(p.at[a].x - p.at[b].x) < half(a) + half(b)).map((b) => `${a} / ${b}`))
      .concat(names.filter((n) => line(n) < 0 || line(n) > h));
  };

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
});
