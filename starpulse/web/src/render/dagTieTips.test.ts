import { describe, expect, it } from "vitest";
import { pivotTip, tieStatus, tieTip, type TipSky } from "./dagTieTips";
import type { Anchor, Orbiter } from "./dagTies";
import type { Dag } from "../api";

const dag = (name: string, status: Dag["status"]): Dag => ({ name, status, runId: "r", startedAt: "", finishedAt: "", schedule: [], stats: null, rerun: null, startUrl: "", steps: [] });
const sky = {
  dagBy: { "temporal/main-follow": { ...dag("temporal/main-follow", "running"), finishedAt: "2026-10-07T16:12:00Z" }, "temporal/apply-on-merge": dag("temporal/apply-on-merge", "failed"), "temporal/backlog-sweep": dag("temporal/backlog-sweep", "succeeded") },
  cues: [{ dag: "temporal/apply-on-merge", event: "MERGED", on: "each merge", resolves: "forced", state: "done" }],
  board: { machine: { transitions: [{ source: "review", target: "done", event: "MERGED" }] } },
} as unknown as TipSky;
const anchor = (kind: Anchor["kind"], event: string) => ({ kind, event, state: "done" }) as Anchor;
const orb = (name: string, ...anchors: Anchor[]) => ({ dag: `temporal/${name}`, label: name, anchors, primary: anchors[0], subs: [] }) as unknown as Orbiter;
const stateName = (id: string) => ({ done: "Done" })[id as "done"] ?? id;
const plain = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

describe("a tied DAG's status", () => {
  it("is running while it runs, failed · unresolved after a failed run, and its status otherwise", () => {
    expect([sky.dagBy["temporal/main-follow"], sky.dagBy["temporal/apply-on-merge"], sky.dagBy["temporal/backlog-sweep"]].map(tieStatus)).toEqual(["running", "failed · unresolved", "succeeded"]);
    expect(tieStatus(undefined)).toBe("");
  });
});

describe("a hangar's tooltip", () => {
  const html = pivotTip({ state: "done", orbs: [orb("main-follow", anchor("write", "MERGED")), orb("apply-on-merge", anchor("cue", "MERGED"))] }, { sky, stateName });

  it("says what a click and a right-click do", () => {
    expect(plain(html)).toContain("click opens their Ledger · right-click comes back");
  });

  it("names each DAG with its status and whether it writes or is cued", () => {
    expect(plain(html)).toContain("main-follow writes MERGED · running");
    expect(plain(html)).toContain("apply-on-merge cued by MERGED · failed · unresolved");
  });
});

describe("an orbiter's tooltip", () => {
  const ctx = (ev: string | null) => ({ sky, stateName, ev, last: () => "" });

  it("names its DAG's status and the Ledger a click opens", () => {
    const html = plain(tieTip(orb("main-follow", anchor("write", "MERGED")), ctx("MERGED")));
    expect(html).toContain("DAG tied to the Board · running · click for the MERGED Ledger");
    expect(html).toContain("writes MERGED review → Done");
  });

  it("says there is no Ledger to open when none of its transitions has one", () => {
    expect(plain(tieTip(orb("main-follow", anchor("write", "NOPE")), ctx(null)))).toContain("running · no Ledger to open");
  });

  it("says how a cued DAG's failed run clears", () => {
    expect(plain(tieTip(orb("apply-on-merge", anchor("cue", "MERGED")), ctx("MERGED")))).toContain("failed · unresolved · click for the MERGED Ledger");
    expect(plain(tieTip(orb("apply-on-merge", anchor("cue", "MERGED")), ctx("MERGED")))).toContain("a failed run clears only on a green forced rerun");
  });

  it("names the machine it writes the states of and its last run", () => {
    const o = { ...orb("main-follow", anchor("write", "MERGED")), subs: [{ flow: "investigating", x: 0, y: 0 }] } as Orbiter;
    const html = plain(tieTip(o, { ...ctx("MERGED"), last: () => "last run 09:12 MST" }));
    expect(html).toContain("writes the states of investigating");
    expect(html).toContain("last run 09:12 MST");
  });

  it("escapes a DAG name", () => {
    expect(tieTip({ ...orb("x", anchor("write", "MERGED")), dag: "temporal/<b>" } as Orbiter, ctx(null))).toContain("temporal/&lt;b&gt;");
  });
});
