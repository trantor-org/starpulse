import { describe, expect, it } from "vitest";
import { ledgerTop, type LedgerFrame, type LedgerLabel, type LedgerMachine, type LedgerTop } from "./machineLedger";

// The live In Progress machine: one spine, Checkpointed reachable straight from Worktree ready or through Red proven.
const ids = ["start", "worktree_ready", "red_proven", "green", "checkpointed", "docs_reconciled", "lint_green", "committed", "pushed", "pr_opened", "ci_green", "pr_ready", "review_recorded", "needs_attention"];
const name = (id: string) => id.replace(/^./, (c) => c.toUpperCase()).replace(/_/g, " ");
const edges = [
  "start>worktree_ready", "worktree_ready>red_proven", "worktree_ready>checkpointed", "red_proven>green", "green>checkpointed", "checkpointed>docs_reconciled", "docs_reconciled>lint_green",
  "lint_green>committed", "committed>pushed", "pushed>pr_opened", "pr_opened>ci_green", "pr_opened>needs_attention", "ci_green>needs_attention", "ci_green>pr_ready", "pr_ready>review_recorded",
];
const TASKS = { worktree_ready: 9, checkpointed: 27, docs_reconciled: 9, lint_green: 2, pushed: 6, pr_opened: 32 };

/** The machine, with `fan` states on one level after Worktree ready (the live shape at 2, a wider branch beyond it), each rejoining at Checkpointed. */
function machine(fan = 2): LedgerMachine {
  const extra = ["spike_run", "repro_written", "design_asked", "deps_pinned", "spec_drafted", "data_migrated"].slice(0, Math.max(0, fan - 2));
  const all = [...ids.slice(0, 4), ...extra, ...ids.slice(4)];
  return {
    states: all.map((id) => ({ id, name: name(id), initial: id === "start", final: id === "review_recorded" || id === "needs_attention" })),
    transitions: [...edges, ...extra.flatMap((x) => [`worktree_ready>${x}`, `${x}>checkpointed`])].map((e) => {
      const [source, target] = e.split(">");
      return { source, target, event: target.toUpperCase() };
    }),
    tasks: TASKS,
    entered: ["pr_opened", "worktree_ready"],
  };
}
const frame = (scale: number, W = 1350, H = 900): LedgerFrame => ({ W, H, scale, measure: (s, px) => s.length * (px * 0.56 + 0.6) });

describe("the machine ledger's top", () => {
  it.each([100, 125])("takes half again its natural height at %i% text, short of 60% of the view", (scale) => {
    const f = frame(scale), top = ledgerTop(machine(), f);
    expect(top.natural).toBeGreaterThan(0);
    expect(top.hdrB).toBeCloseTo(top.natural * 1.5, 5);
    expect(top.hdrB).toBeLessThan(f.H * 0.6);
  });

  it("stops at 60% of the view when half again its height would pass it", () => {
    const natural = ledgerTop(machine(), frame(100)).natural, H = Math.round(natural / 0.48), top = ledgerTop(machine(), frame(100, 1350, H));
    expect(top.hdrB).toBeGreaterThan(top.natural);
    expect(top.hdrB).toBeLessThan(top.natural * 1.5);
    expect(top.hdrB).toBeCloseTo(H * 0.6, 5);
  });

  it("is never shorter than its natural height, even where that passes 60% of the view", () => {
    const top = ledgerTop(machine(6), frame(150, 1350, 640));
    expect(top.natural).toBeGreaterThan(640 * 0.6);
    expect(top.hdrB).toBe(top.natural);
  });
});

const box = (l: LedgerLabel) => ({ x0: l.x, x1: l.x + l.w, y0: l.y, y1: l.y + l.h });
const apart = (a: ReturnType<typeof box>, b: ReturnType<typeof box>) => a.x1 <= b.x0 || b.x1 <= a.x0 || a.y1 <= b.y0 || b.y1 <= a.y0;
/** What the placer promises at any text size: every state named once, inside the top and the lane, over no other name and no state's tasks. */
function named(top: LedgerTop, f: LedgerFrame, every = true) {
  if (every) expect(top.labels.map((l) => l.id).sort()).toEqual(top.nodes.map((n) => n.id).sort());
  for (const l of top.labels) {
    expect(l.x).toBeGreaterThanOrEqual(0);
    expect(l.x + l.w).toBeLessThanOrEqual(f.W);
    expect(l.y).toBeGreaterThanOrEqual(0);
    expect(l.y + l.h).toBeLessThanOrEqual(top.hdrB);
    expect(l.x).toBeGreaterThanOrEqual(top.metaX + top.metaW);
    for (const o of top.labels) if (o !== l) expect(apart(box(l), box(o))).toBe(true);
    for (const n of top.nodes) {
      const dx = Math.max(box(l).x0 - n.x, 0, n.x - box(l).x1), dy = Math.max(box(l).y0 - n.y, 0, n.y - box(l).y1);
      expect(Math.hypot(dx, dy)).toBeGreaterThanOrEqual(n.orbit);
    }
  }
}

describe("the machine ledger's state names", () => {
  it.each([100, 125, 150])("names every state at %i% text on a 1350 and a 1600 px view, with and without a six-way branch", (scale) => {
    for (const W of [1350, 1600]) {
      for (const fan of [2, 6]) {
        const f = frame(scale, W), top = ledgerTop(machine(fan), f);
        named(top, f);
      }
    }
  });

  it("never overprints on a narrow view: the names it cannot place wait for the hover", () => {
    const f = frame(150, 1000), top = ledgerTop(machine(6), f);
    expect(top.labels.length).toBeGreaterThan(top.nodes.length / 2);
    named(top, f, false);
  });

  it("names a column of three or more states beside it, each on its own side of its state", () => {
    const f = frame(100), top = ledgerTop(machine(6), f), col = top.nodes.filter((n) => top.nodes.filter((o) => o.x === n.x).length >= 3);
    expect(col.length).toBeGreaterThanOrEqual(3);
    for (const n of col) {
      const l = top.labels.find((q) => q.id === n.id)!;
      expect(l.tier).toBe(0);
      expect(Math.abs(l.y + l.h / 2 - n.y)).toBeLessThan(l.h / 2);
      expect(l.x >= n.x + n.orbit || l.x + l.w <= n.x - n.orbit).toBe(true);
    }
  });

  it("gives a crowded name a second or third tier on a hairline from its state", () => {
    const f = frame(150), top = ledgerTop(machine(2), f), tiered = top.labels.filter((l) => l.tier > 0);
    expect(tiered.length).toBeGreaterThan(0);
    for (const l of tiered) expect(l.lead).not.toBeNull();
  });
});

describe("the machine ledger under the page's own chrome", () => {
  it("names every state clear of the boxes the page draws over the canvas, and starts its header below them", () => {
    const free = ledgerTop(machine(6), frame(125, 1600)), at = [...free.labels].sort((a, b) => a.y - b.y)[0];
    const chrome = { x0: at.x - 4, y0: at.y - 2, x1: at.x + at.w + 4, y1: at.y + at.h + 2 };
    const top = ledgerTop(machine(6), { ...frame(125, 1600), avoid: [chrome], inset: 56 });
    expect(top.labels).toHaveLength(top.nodes.length);
    for (const l of top.labels) expect(apart(box(l), chrome)).toBe(true);
    expect(top.metaT).toBe(56);
  });
});
