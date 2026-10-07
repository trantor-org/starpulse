import { describe, expect, it } from "vitest";
import { arriveMerge, demoLedger, scenarioOf } from "./demoLedger";
import { markOf } from "./ledger";
import type { Cue, Dag, Machine, Snapshot } from "./types";

const dag = (name: string, steps: string[]): Dag => ({ name, status: "succeeded", runId: "r", startedAt: "", finishedAt: "", steps: steps.map((n, i) => ({ name: n, depends: i ? [steps[i - 1]] : [], status: "succeeded" })) });
const machine = (): Machine => ({
  states: ["review", "done"].map((id, i) => ({ id, name: id, initial: !i, final: !!i })),
  transitions: [{ source: "review", target: "done", event: "MERGED" }],
  writers: { MERGED: [{ actor: "main-follow", trigger: "push" }] }, dagActors: ["main-follow"], mainLine: ["review", "done"],
} as Machine);
const cues: Cue[] = [{ dag: "apply-on-merge", event: "MERGED", state: "done", on: "each merge", resolves: "forced" }];
const snap = (over: Partial<Snapshot> = {}): Snapshot => ({
  graphs: ["board"], flows: [{ name: "board", agents: [], machine: machine() }], cues, settled: {}, error: null, now: 1000,
  dags: [dag("main-follow", ["checkout", "push"]), dag("apply-on-merge", ["classify", "apply_deploy", "verify"])], ...over,
});
const NOW = 10_000;

describe("scenarioOf", () => {
  it("reads the page's ?ms= and falls back to live", () => {
    expect([scenarioOf("?ms=cross"), scenarioOf("?ms=infer"), scenarioOf("?ms=fail"), scenarioOf("?ms=nope"), scenarioOf("")]).toEqual(["cross", "infer", "fail", "live", "live"]);
  });
});

describe("demoLedger", () => {
  it("has no rows for a Board no DAG is tied to MERGED on", () => {
    expect(demoLedger(snap({ cues: [], flows: [{ name: "board", agents: [], machine: { ...machine(), writers: {}, dagActors: [] } }] }), NOW, "live")).toEqual([]);
  });

  it("holds the merges of the last day newest first, each with a run for every tied DAG and the newest still running", () => {
    const rows = demoLedger(snap(), NOW, "live");

    expect(rows.length).toBeGreaterThan(5);
    expect(rows.map((r) => r.at)).toEqual([...rows.map((r) => r.at)].sort((a, b) => b - a));
    expect(Object.keys(rows[1].runs)).toEqual(["main-follow", "apply-on-merge"]);
    expect(rows[0].runs["apply-on-merge"].status).toBe("running");
    expect(rows[0].runs["apply-on-merge"].step).not.toBe("");
    expect(rows.slice(1).every((r) => r.runs["apply-on-merge"].status === "succeeded")).toBe(true);
    expect(rows.every((r) => markOf(r.runs["apply-on-merge"]) === "keyed")).toBe(true);
  });

  it("pairs every run by time in the infer scenario, some with another merge in their window", () => {
    const marks = demoLedger(snap(), NOW, "infer").flatMap((r) => Object.values(r.runs).map(markOf));

    expect(new Set(marks)).toEqual(new Set(["inferred", "ambiguous"]));
  });

  it("fails and pins one apply in the fail scenario", () => {
    const rows = demoLedger(snap(), NOW, "fail"), failed = rows.filter((r) => r.pinned);

    expect(failed).toHaveLength(1);
    expect(failed[0].fails["apply-on-merge"]).toMatchObject({ resolves: "forced", resolved: null });
    expect(failed[0].runs["apply-on-merge"].status).toBe("failed");
  });

  it("adds another repository's merges in the cross scenario: one a pin bump applied, one still waiting for its bump", () => {
    const rows = demoLedger(snap(), NOW, "cross"), kids = rows.filter((r) => r.appliedBy !== undefined), bump = rows.find((r) => r.applies?.length);

    expect(kids.map((r) => r.appliedBy)).toEqual([null, bump!.key]);
    expect(bump!.applies).toEqual([kids[1].key]);
    expect(kids.every((r) => Object.keys(r.runs).length === 0)).toBe(true);
    expect(rows.filter((r) => r.appliedBy === undefined).every((r) => r.key.length >= 7)).toBe(true);
  });
});

describe("arriveMerge", () => {
  it("settles the runs in flight and lands a new merge on top with its writer running", () => {
    const s = snap(), rows = demoLedger(s, NOW, "live"), next = arriveMerge(s, rows, NOW + 25);

    expect(next).toHaveLength(rows.length + 1);
    expect(next[0].at).toBe(NOW + 25);
    expect(next[0].key).not.toBe(rows[0].key);
    expect(next[0].runs["main-follow"].status).toBe("running");
    expect(next[0].runs["apply-on-merge"].status).toBe("queued");
    expect(next[1].runs["apply-on-merge"].status).toBe("succeeded");
    expect(rows[0].runs["apply-on-merge"].status).toBe("running");
  });
});
