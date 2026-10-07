import { describe, expect, it } from "vitest";
import { BOARD, drill, pathKey } from "./levels";
import { ledgerLevel, pathLedger } from "./levels";
import { ledgerOf } from "./ledger";
import type { Snapshot } from "./types";

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

  it("is what drilling the fold on the Review → Done path pushes", () => {
    const level = ledgerLevel(snap(), "MERGED")!;

    expect(drill({ name: "3 DAGs", fold: level.dags }, level.crit, level.path)).toEqual({ push: { kind: "fold", dags: level.dags, crit: level.crit, path: level.path } });
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
      { dag: "dagu/main-follow", role: "writer", on: "bin/board_reconcile_merged.py", resolves: null },
      { dag: "dagu/apply-on-merge", role: "cue", on: "push to main", resolves: "forced" },
      { dag: "dagu/graph-refresh", role: "cue", on: "push to main", resolves: "next" },
    ]);
  });

  it("gives a merge a row of its merge, pull request and commit, and any other event a row of its task", () => {
    const rows = (event: string) => ledgerOf(snap(), ledgerLevel(snap(), event)!)!.rows;

    expect([rows("MERGED"), rows("CLAIM")]).toEqual(["merge", "task"]);
  });

  it("names the event a Board fold's path carries by the DAGs it holds, when the fold is drilled from the Board", () => {
    const fold = { kind: "fold" as const, dags: ["dagu/main-follow", "dagu/graph-refresh"], crit: [], path: ["review", "done"] as [string, string] };

    expect(ledgerOf(snap(), fold)!.event).toBe("MERGED");
    expect(ledgerOf(snap(), { ...fold, path: ["ready", "review"] })).toBeNull();
    expect(ledgerOf(snap(), { ...fold, path: null })).toBeNull();
  });
});
