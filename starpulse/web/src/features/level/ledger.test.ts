import { describe, expect, it } from "vitest";
import { BOARD, pathKey } from "../../render/levels";
import { ledgerLevel, pathLedger } from "../../render/levels";
import { freshKeys, ledgerOf, markOf, optionalSteps, shortApplied, statusLine, tiesOf, worst, type LineCtx, type Tie } from "./ledger";
import type { LedgerRow, LedgerRun, Snapshot } from "../../api";

const states = ["ready", "in_progress", "review", "done"].map((id, i) => ({ id, name: id === "in_progress" ? "In Progress" : id[0].toUpperCase() + id.slice(1), initial: i === 0, final: false }));
/** A Board whose CLAIM is written by one DAG, REVIEW by none and MERGED by main-follow with two cues. */
const snap = (): Pick<Snapshot, "flows" | "cues"> => ({
  flows: [{
    name: "board", agents: [],
    machine: {
      states,
      transitions: [
        { source: "ready", target: "in_progress", event: "CLAIM" }, { source: "in_progress", target: "review", event: "REVIEW" },
        { source: "review", target: "done", event: "MERGED" }, { source: "in_progress", target: "in_progress", event: "STAY" },
      ],
      writers: { CLAIM: [{ actor: "dagu/autopilot", trigger: "dagu" }, { actor: "operator", trigger: "ui" }], MERGED: [{ actor: "dagu/main-follow", trigger: "bin/board_reconcile_merged.py" }], STAY: [{ actor: "dagu/stayer", trigger: "dagu" }] },
      dagActors: ["dagu/autopilot", "dagu/main-follow", "dagu/stayer"],
    },
  }],
  cues: [
    { dag: "dagu/apply-on-merge", event: "MERGED", state: "done", on: "push to main", resolves: "forced" },
    { dag: "dagu/graph-refresh", event: "MERGED", state: "done", on: "push to main", resolves: "next" },
    { dag: "dagu/notifier", event: "CLAIM", state: "in_progress", on: "each claim", resolves: "next" },
  ],
});

describe("the DAGs tied to an event", () => {
  it("carry the grace a cue declares for its run to start, and none for a writer", () => {
    const s = snap();
    s.cues![0] = { ...s.cues![0], grace: 120 };

    expect(tiesOf(s, "MERGED").map((t) => [t.dag, t.grace])).toEqual([["dagu/main-follow", null], ["dagu/apply-on-merge", 120], ["dagu/graph-refresh", null]]);
  });
});

describe("a Board transition's Ledger level", () => {
  it("opens over the path MERGED takes, holding the DAG that writes it and the DAGs it cues", () => {
    const level = ledgerLevel(snap(), "MERGED")!;

    expect(level).toEqual({
      kind: "fold", event: "MERGED", path: ["review", "done"], dags: ["dagu/main-follow", "dagu/apply-on-merge", "dagu/graph-refresh"],
      crit: [
        "dagu/main-follow: writes MERGED (Review → Done)",
        "dagu/apply-on-merge: runs on push to main, beside MERGED (Review → Done)",
        "dagu/graph-refresh: runs on push to main, beside MERGED (Review → Done)",
      ],
    });
    expect(pathKey([...BOARD, level])).toBe("board/dagu/main-follow+dagu/apply-on-merge+dagu/graph-refresh");
  });

  it("opens for every Board transition a DAG writes or is cued by, not only MERGED", () => {
    const level = ledgerLevel(snap(), "CLAIM")!;

    expect(level).toMatchObject({ kind: "fold", event: "CLAIM", path: ["ready", "in_progress"], dags: ["dagu/autopilot", "dagu/notifier"] });
    // an event no DAG writes or is cued by has no Ledger, and nor has one that leaves its state where it was
    expect(ledgerLevel(snap(), "REVIEW")).toBeNull();
    expect(ledgerLevel(snap(), "STAY")).toBeNull();
    expect(ledgerLevel(snap(), "NOPE")).toBeNull();
  });
});

describe("a Board path's Ledger", () => {
  it("is the first of the path's events that a DAG is tied to, so a path whose first event has no DAG still opens one", () => {
    expect(pathLedger(snap(), ["REVIEW", "MERGED"])).toEqual(ledgerLevel(snap(), "MERGED"));
    expect(pathLedger(snap(), ["CLAIM", "MERGED"])).toMatchObject({ event: "CLAIM" });
    expect(pathLedger(snap(), ["REVIEW", "STAY"])).toBeNull();
  });
});

describe("a Ledger's frame", () => {
  it("lists the writer first, then each cue in the order the machine declares them, with the contract each states", () => {
    const l = ledgerOf(snap(), ledgerLevel(snap(), "MERGED")!)!;

    expect([l.event, l.from, l.to]).toEqual(["MERGED", "review", "done"]);
    expect(l.ties).toEqual([
      { dag: "dagu/main-follow", role: "writer", on: "bin/board_reconcile_merged.py", resolves: null, grace: null },
      { dag: "dagu/apply-on-merge", role: "cue", on: "push to main", resolves: "forced", grace: null },
      { dag: "dagu/graph-refresh", role: "cue", on: "push to main", resolves: "next", grace: null },
    ]);
  });

  it("gives a merge a row of its merge, pull request and commit, and any other event a row of its task", () => {
    const rows = (event: string) => ledgerOf(snap(), ledgerLevel(snap(), event)!)!.rows;

    expect([rows("MERGED"), rows("CLAIM")]).toEqual(["merge", "task"]);
  });

  it("names the event a Board fold's path carries by the DAGs it holds, when the fold is entered from a Board path", () => {
    const fold = { kind: "fold" as const, dags: ["dagu/main-follow", "dagu/graph-refresh"], crit: [], path: ["review", "done"] as [string, string] };

    expect(ledgerOf(snap(), fold)!.event).toBe("MERGED");
    expect(ledgerOf(snap(), { ...fold, path: ["ready", "review"] })).toBeNull();
    expect(ledgerOf(snap(), { ...fold, path: null })).toBeNull();
  });
});

const iso = (sec: number) => new Date(sec * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const hm = (sec: number) => `t${sec % 1000}`;
const run = (over: Partial<LedgerRun> = {}): LedgerRun => ({ runId: "r", status: "succeeded", startedAt: iso(1000), finishedAt: iso(1042), steps: {}, step: "", inferred: false, ambiguous: 0, ...over });
const merge = (over: Partial<LedgerRow> = {}): LedgerRow => ({ key: "a1b2c3d4e5", at: 990, tasks: ["TASK-1"], sha: "a1b2c3d4e5", pr: { repo: "trantor", number: 7, url: "u" }, runs: {}, fails: {}, pinned: false, ...over });
const writer: Tie = { dag: "dagu/main-follow", role: "writer", on: "push", resolves: null, grace: null };
const cue: Tie = { dag: "dagu/apply-on-merge", role: "cue", on: "push", resolves: "forced", grace: null };
const ctx = (over: Partial<LineCtx> = {}): LineCtx => ({ event: "MERGED", now: 1100, hm, optional: new Set(), by: () => undefined, ...over });

describe("a run's mark", () => {
  it("is keyed when the run named its commit, inferred when time paired it, and ambiguous when it is inferred and another merge landed in its window", () => {
    expect([markOf(run()), markOf(run({ inferred: true })), markOf(run({ inferred: true, ambiguous: 2 })), markOf(undefined)]).toEqual(["keyed", "inferred", "ambiguous", "keyed"]);
  });
});

describe("a merge row's status line", () => {
  it("says a succeeded run took its duration, and a writer's sub-line names the event it wrote", () => {
    expect(statusLine(merge(), writer, run(), ctx())).toEqual({ main: "✓ 42 s", sub: "MERGED t990", state: "succeeded", mark: "keyed" });
  });

  it("says a running run is in its step for as long as it has run", () => {
    expect(statusLine(merge(), cue, run({ status: "running", finishedAt: "", step: "apply_images" }), ctx())).toMatchObject({ main: "apply_images · 1:40", state: "running" });
  });

  it("names the step a failed run stopped at, and a queued run is queued", () => {
    const fails = { [cue.dag]: { runId: "r", step: "apply_deploy", startedAt: iso(1000), finishedAt: iso(1042), resolves: "forced" as const, resolved: null } };

    expect(statusLine(merge({ fails }), cue, run({ status: "failed" }), ctx())).toMatchObject({ main: "✕ apply_deploy · 42 s", state: "failed" });
    expect(statusLine(merge(), cue, run({ status: "queued", finishedAt: "" }), ctx()).main).toBe("queued");
  });

  it("gives a queued run that has not started no start time", () => {
    expect(statusLine(merge(), cue, run({ status: "queued", startedAt: "", finishedAt: "" }), ctx()).sub).toBe("");
  });

  it("lists, for a cue, the optional steps the run applied, and its start time when it applied none", () => {
    const steps = { classify: "succeeded", apply_deploy: "succeeded", apply_skills_a: "skipped", verify: "succeeded" } as const;

    expect(statusLine(merge(), cue, run({ steps }), ctx({ optional: new Set(["apply_deploy", "apply_skills_a"]) })).sub).toBe("deploy");
    expect(statusLine(merge(), cue, run({ steps }), ctx()).sub).toBe("t0");
  });

  it("marks a run paired by time with ≈, counting the merges in its window when another landed", () => {
    expect(statusLine(merge(), cue, run({ inferred: true }), ctx())).toMatchObject({ sub: "≈ t0", mark: "inferred" });
    expect(statusLine(merge(), cue, run({ inferred: true, ambiguous: 1 }), ctx())).toMatchObject({ sub: "≈ 2 in window · t0", mark: "ambiguous" });
  });

  it("says a merge no run has paired with yet has no run", () => {
    expect(statusLine(merge(), cue, undefined, ctx())).toEqual({ main: "no run yet", sub: "", state: null, mark: "keyed" });
  });

  it("says a cue that has not started once its grace window since the merge has passed is overdue, not waiting", () => {
    const timed: Tie = { ...cue, grace: 300 };

    expect(statusLine(merge(), timed, undefined, ctx({ now: 990 + 300 }))).toMatchObject({ main: "no run yet", state: null });
    expect(statusLine(merge(), timed, undefined, ctx({ now: 990 + 301 }))).toEqual({ main: "overdue", sub: "no run in 5:01", state: "overdue", mark: "keyed" });
    // a writer has no grace, and a cue's own run, however late, is that run's state
    expect(statusLine(merge(), writer, undefined, ctx({ now: 99999 })).state).toBeNull();
    expect(statusLine(merge(), timed, run({ startedAt: iso(5000), finishedAt: iso(5042) }), ctx({ now: 99999 })).state).toBe("succeeded");
  });

  it("keeps another repository's unapplied merge waiting however old, since its cue starts at the pin bump", () => {
    expect(statusLine(merge({ appliedBy: null }), { ...cue, grace: 300 }, undefined, ctx({ now: 99999 }))).toMatchObject({ main: "waits for its pin bump", state: "waiting" });
  });

  it("says another repository's merge is applied by its pin bump, once a parent merge includes it, and waits for one before", () => {
    const parent = merge({ key: "p", sha: "ffeeddcc99", at: 1050 });

    expect(statusLine(merge({ appliedBy: "p" }), cue, undefined, ctx({ by: (k) => (k === "p" ? parent : undefined) }))).toEqual({ main: "applied by its pin bump ffeeddc", sub: "t50", state: "waiting", mark: "keyed" });
    expect(statusLine(merge({ appliedBy: null }), cue, undefined, ctx())).toMatchObject({ main: "waits for its pin bump", state: "waiting" });
  });
});

describe("the steps a cue applies only sometimes", () => {
  it("are those some loaded row's run skipped", () => {
    const rows = [merge({ runs: { [cue.dag]: run({ steps: { a: "succeeded", b: "skipped", c: "succeeded" } }) } }), merge({ runs: { [cue.dag]: run({ steps: { a: "succeeded", b: "succeeded", c: "skipped" } }) } }), merge()];

    expect([...optionalSteps(rows, cue.dag)].sort()).toEqual(["b", "c"]);
    expect(shortApplied(rows[0].runs[cue.dag], optionalSteps(rows, cue.dag))).toBe("c");
  });
});

describe("a row's worst state", () => {
  const runs = (...statuses: LedgerRun["status"][]) => Object.fromEntries(statuses.map((s, i) => [`d${i}`, run({ status: s })]));

  it("is failed over running over queued over succeeded", () => {
    expect([["succeeded", "failed", "running"], ["succeeded", "running"], ["queued", "succeeded"], ["succeeded"]].map((s) => worst(merge({ runs: runs(...(s as LedgerRun["status"][])) })))).toEqual(["failed", "running", "queued", "succeeded"]);
  });

  it("is waiting for another repository's merge until a pin bump applies it, then what the bump's runs are", () => {
    const parent = merge({ key: "p", runs: runs("running") });

    expect([worst(merge({ appliedBy: null })), worst(merge({ appliedBy: "p" }), parent), worst(merge({ appliedBy: "p" }), undefined)]).toEqual(["waiting", "running", "waiting"]);
  });
});

describe("the rows that just arrived", () => {
  const rows = [merge({ key: "n" }), merge({ key: "o" })];

  it("are none on the first look, whatever the Ledger holds", () => {
    expect(freshKeys(null, rows)).toEqual([]);
  });

  it("are the keys the last look did not hold, so a reload or a scroll-in never replays one", () => {
    expect(freshKeys(new Set(["o"]), rows)).toEqual(["n"]);
    expect(freshKeys(new Set(["n", "o"]), rows)).toEqual([]);
  });
});
