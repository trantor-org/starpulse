import { describe, expect, it } from "vitest";
import { bannerOf, doctorTip, failHtml, focusRow, junctionTip, mergePanel, mergeTip, stepStates, stepTip, type PanelCtx } from "./ledgerPanel";
import type { Tie } from "./ledger";
import type { ContractCheck, ContractReport, LedgerFail, LedgerRow, LedgerRun } from "./api";

const iso = (s: number) => new Date(s * 1000).toISOString().replace(/\.\d+Z$/, "Z");
const ties: Tie[] = [
  { dag: "main-follow", role: "writer", on: "push", resolves: null },
  { dag: "apply-on-merge", role: "cue", on: "each merge", resolves: "forced" },
  { dag: "graph-refresh", role: "cue", on: "each merge", resolves: "next" },
];
const run = (over: Partial<LedgerRun> = {}): LedgerRun => ({ runId: "r", status: "succeeded", startedAt: iso(1000), finishedAt: iso(1042), steps: { build: "succeeded", apply: "succeeded" }, step: "", inferred: false, ambiguous: 0, ...over });
const fail = (over: Partial<LedgerFail> = {}): LedgerFail => ({ runId: "r", step: "apply", startedAt: iso(1000), finishedAt: iso(1042), resolves: "forced", resolved: null, ...over });
const row = (over: Partial<LedgerRow> = {}): LedgerRow => ({ key: "abc", at: 990, tasks: ["TASK-7"], sha: "abc1234567", pr: { repo: "trantor", number: 77, url: "u" }, runs: {}, fails: {}, pinned: false, ...over });
const ctx = (over: Partial<PanelCtx> = {}): PanelCtx => ({
  event: "MERGED", from: "Review", to: "Done", ties,
  steps: { "main-follow": ["only"], "apply-on-merge": ["build", "apply"], "graph-refresh": ["index"] },
  optional: {}, palette: { succeeded: "#34d399", failed: "#fb7185", not_started: "#334155" }, now: 2000, hm: (s) => `t${s % 1000}`, by: () => undefined, task: (id) => `<a>${id}</a>`, ...over,
});

describe("failHtml", () => {
  it("names each failed cue's step and says when and by what its failure was resolved, or that it is not", () => {
    const html = failHtml(row({ fails: {
      "apply-on-merge": fail(),
      "graph-refresh": fail({ step: "index", resolves: "next", resolved: { runId: "n", at: iso(1500) } }),
    } }), ctx(), "note");

    expect(html).toContain("apply-on-merge ✕ apply: unresolved, clears on a forced rerun");
    expect(html).toContain("graph-refresh ✕ index: resolved t500 by the next success");
    expect(html.match(/class="note"/g)).toHaveLength(2);
  });

  it("says nothing for a merge no run failed", () => {
    expect(failHtml(row(), ctx(), "note")).toBe("");
  });
});

describe("mergePanel", () => {
  const panel = mergePanel(row({
    runs: { "main-follow": run({ steps: {} }), "apply-on-merge": run({ status: "failed", steps: { build: "succeeded", apply: "failed" } }), "graph-refresh": run({ inferred: true, ambiguous: 2, steps: { index: "succeeded" } }) },
    fails: { "apply-on-merge": fail() },
  }), ctx());

  it("opens on the task and the commit, with a close control", () => {
    expect(panel).toContain('class="x"');
    expect(panel).toContain("merge to trantor · t990");
    expect(panel).toContain("<a>TASK-7</a>");
    expect(panel).toContain("trantor #77 · abc1234");
    expect(panel).toContain("Review → Done: main-follow wrote MERGED");
  });

  it("lists each cued run with its state, window, how it was paired and a chip per step coloured by its state", () => {
    expect(panel).toContain("apply-on-merge");
    expect(panel).toMatch(/failed<\/b> · t0–t42 · 42 s/);
    expect(panel).toContain("paired by commit: AFTER=abc1234");
    expect(panel).toContain("≈ paired by time: the newest merge before the run started; 2 more merges landed first, so it may be theirs");
    expect(panel).toMatch(/class="chip" style="color:#fb7185[^"]*" title="failed">apply</);
    expect(panel).toMatch(/style="color:#34d399[^"]*" title="succeeded">build</);
  });

  it("closes on the failure text", () => {
    expect(panel).toContain("apply-on-merge ✕ apply: unresolved, clears on a forced rerun");
  });

  it("says why a merge of another repository has no run, and which pin bump applied it", () => {
    const bump = row({ key: "bbb", at: 1200, sha: "bbbbbbbbbb", tasks: [], applies: ["x"] });
    const cross = mergePanel(row({ appliedBy: "bbb", pr: { repo: "skills", number: 9, url: "u" } }), ctx({ by: (k) => (k === "bbb" ? bump : undefined) }));

    expect(cross).toContain("starts no run here");
    expect(cross).toContain("applied by its pin bump bbbbbbb");
  });
});

describe("mergePanel's rerun control", () => {
  const failing = row({ fails: { "apply-on-merge": fail(), "graph-refresh": fail({ step: "index", resolves: "next", resolved: { runId: "n", at: iso(1500) } }) } });

  it("offers a Force rerun for each DAG whose failure is unresolved, and none for a resolved one", () => {
    const html = mergePanel(failing, ctx());

    expect(html).toContain('<button class="run" data-rerun="apply-on-merge">↻ Force rerun apply-on-merge</button>');
    expect(html).not.toContain('data-rerun="graph-refresh"');
  });

  it("offers none on a merge no run failed on", () => {
    expect(mergePanel(row(), ctx())).not.toContain("data-rerun");
  });

  it("shows a rerun being asked for as busy and disabled", () => {
    const html = mergePanel(failing, ctx({ rerun: { busy: new Set(["apply-on-merge"]), refused: {} } }));

    expect(html).toContain('<button class="run" data-rerun="apply-on-merge" disabled>↻ Rerunning apply-on-merge…</button>');
  });

  it("shows the server's refusal under the button, escaped", () => {
    const html = mergePanel(failing, ctx({ rerun: { busy: new Set(), refused: { "apply-on-merge": "apply-on-merge has no <unresolved> failure" } } }));

    expect(html).toContain('data-rerun="apply-on-merge">↻ Force rerun');
    expect(html).toContain('<div class="note" style="color:#fb7185">apply-on-merge has no &lt;unresolved&gt; failure</div>');
  });
});

const report = (...checks: ContractCheck[]): ContractReport => ({ ok: checks.every((c) => c.status !== "fail"), checks });
const check = (name: string, status: ContractCheck["status"], reason = `${name} ${status}`): ContractCheck => ({ check: name, status, reason });

describe("bannerOf", () => {
  it("shows nothing until a report lists a check", () => {
    expect(bannerOf(null)).toBeNull();
    expect(bannerOf(report())).toBeNull();
  });

  it("is green when every check passes", () => {
    expect(bannerOf(report(check("cue:a", "pass"), check("repo:c", "pass")))).toEqual({ tone: "ok", head: "✓ doctor · contract matches runs", sub: "writers, cues and commit keys" });
  });

  it("is amber for a warning, which is a cue with no commit key", () => {
    expect(bannerOf(report(check("cue:a", "warn"), check("repo:c", "pass")))).toMatchObject({ tone: "warn", head: "⚠ doctor · no commit key declared", sub: "runs pair with merges by time" });
  });

  it("is red when a check fails, naming the checks that did", () => {
    expect(bannerOf(report(check("cue:a", "warn"), check("cue:b", "fail"), check("repo:c", "fail")))).toEqual({ tone: "fail", head: "✕ doctor · 2 contract checks fail", sub: "cue:b, repo:c" });
    expect(bannerOf(report(check("repo:c", "fail")))?.head).toBe("✕ doctor · 1 contract check fails");
  });
});

describe("doctorTip", () => {
  it("lists each check with its mark and why, and shows the key to declare when one is missing", () => {
    const tip = doctorTip(report(check("cue:a", "pass", "a declares AFTER"), check("cue:b", "warn", "b has no after key"), check("repo:c", "fail", "child <is not> a submodule")));

    expect(tip).toContain("starpulse doctor · contract");
    expect(tip).toContain('<div class="n">1 contract check fails</div>');
    expect(tip).toContain("✓ cue:a — a declares AFTER");
    expect(tip).toContain("⚠ cue:b — b has no after key");
    expect(tip).toContain("✕ repo:c — child &lt;is not&gt; a submodule");
    expect(tip).toContain("[runs.commit]");
  });

  it("leaves the key out when no cue lacks one", () => {
    expect(doctorTip(report(check("cue:a", "pass")))).not.toContain("[runs.commit]");
  });
});

describe("mergeTip", () => {
  const withRuns = row({
    runs: { "main-follow": run({ steps: {} }), "apply-on-merge": run({ status: "failed", steps: { build: "succeeded", apply: "failed" } }) },
    fails: { "apply-on-merge": fail() },
  });

  it("names the merge and gives each tied DAG's status line, then the failure and the click hint", () => {
    const tip = mergeTip(withRuns, ctx());

    expect(tip).toContain("merge to trantor · t990 · #77 · abc1234");
    expect(tip).toContain('<div class="n">TASK-7</div>');
    expect(tip).toMatch(/apply-on-merge: ✕ apply · 42 s/);
    expect(tip).toContain("graph-refresh: no run yet");
    expect(tip).toContain("apply-on-merge ✕ apply: unresolved");
    expect(tip).toContain("click for its runs");
  });

  it("explains that another repository's merge waits for the pin bump", () => {
    expect(mergeTip(row({ appliedBy: null, pr: { repo: "skills", number: 9, url: "u" } }), ctx())).toContain("nothing applies until the pin bump");
  });
});

describe("stepTip", () => {
  it("states the step's state in the merge it is read against, and what it follows", () => {
    const tip = stepTip("apply-on-merge", "apply", ["build"], row({ runs: { "apply-on-merge": run({ steps: { build: "succeeded", apply: "failed" } }) } }), ctx());

    expect(tip).toContain("step of apply-on-merge · after build");
    expect(tip).toContain('<div class="n">apply</div>');
    expect(tip).toContain("failed in the t990 merge (abc1234)");
  });

  it("says to hover a merge when none is in view", () => {
    expect(stepTip("apply-on-merge", "build", [], undefined, ctx())).toContain("hover a merge to see its run here");
  });
});

describe("junctionTip", () => {
  it("counts the merges of the last hour and says what a merge sets going", () => {
    const tip = junctionTip([row({ at: 4990 }), row({ key: "b", at: 4500 }), row({ key: "c", at: 100 })], ctx({ now: 5000 }));

    expect(tip).toContain("merge to main · 2 in the last hour");
    expect(tip).toContain("main-follow runs on the push and writes MERGED, moving the task Review → Done");
    expect(tip).toContain("apply-on-merge and graph-refresh");
  });
});

describe("stepStates", () => {
  it("gives a merge's state for each step of a template, a one-step template taking its run's", () => {
    const r = row({ runs: { "apply-on-merge": run({ steps: { build: "succeeded" } }), "main-follow": run({ status: "running", steps: {} }) } });

    expect(stepStates(r, "apply-on-merge", ["build", "apply"])).toEqual({ build: "succeeded", apply: "not_started" });
    expect(stepStates(r, "main-follow", ["only"])).toEqual({ only: "running" });
  });

  it("is null for a merge with no run of the DAG", () => {
    expect(stepStates(row(), "apply-on-merge", ["build"])).toBeNull();
    expect(stepStates(undefined, "apply-on-merge", ["build"])).toBeNull();
  });
});

describe("focusRow", () => {
  const rows = [row({ key: "x", appliedBy: null }), row({ key: "main" }), row({ key: "old" })];

  it("prefers the hovered merge, then the open one, then the newest merge of the main repository", () => {
    expect(focusRow(rows[2], rows[0], rows)).toBe(rows[2]);
    expect(focusRow(null, rows[2], rows)).toBe(rows[2]);
    expect(focusRow(null, null, rows)).toBe(rows[1]);
    expect(focusRow(null, null, [])).toBeUndefined();
  });
});
