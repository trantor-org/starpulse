import { describe, expect, it } from "vitest";
import type { MachineEvent } from "../../api/types.gen";
import { jobAt } from "./sunsEngine";
import { css, jobOf, sceneOf, type View } from "./sunsScene";

const NOW = 1_800_000_000;
const ev = (ago: number, machine: string, from: string, to: string): MachineEvent => ({ at: NOW - ago * 60, machine, event: "E", from, to });
const view = (sel: string): View => ({ sel, open: {}, pick: {}, hover: null, det: null, at: null, replaying: false });
const texts = (s: ReturnType<typeof sceneOf>) => [...s.main.T, ...s.rows.T].map((t) => t.text);

// Build for 40 minutes, the four lenses (Security asks for changes), Build round 2, then Deliver for the last 5 minutes.
const story = [
  ev(60, "build", "start", "worktree_ready"),
  ev(20, "security", "idle", "running"), ev(19, "ux", "idle", "pass"), ev(18, "ui", "idle", "pass"), ev(17, "code", "idle", "pass"),
  ev(16, "security", "running", "fail"),
  ev(15, "in-progress", "deliver", "build"),
  ev(5, "in-progress", "build", "deliver"), ev(5, "deliver", "start", "lint_green"),
];

describe("sunsScene", () => {
  it("turns a style string into React style properties", () => {
    expect(css("position:absolute;left:3px;background:linear-gradient(90deg,#fff 0%,rgba(0,0,0,.1) 0);--k:1")).toEqual({
      position: "absolute", left: "3px", background: "linear-gradient(90deg,#fff 0%,rgba(0,0,0,.1) 0)", "--k": "1",
    });
  });

  it("starts a task with no events in Build, round 1, at its first step, coloured by its agent tier", () => {
    expect(jobOf("T", "t", undefined, [], NOW)).toMatchObject({ id: "T", title: "t", phase: "build", round: 1, step: 0, tier: "standard", trail: [{ phase: "build", round: 1 }] });
    expect(jobOf("T", "t", "@agent-deep-high", [], NOW).tier).toBe("deep");
  });

  it("follows the task through its phases: a lens round is QA, a return to Build starts round 2, and the step is the phase machine's state", () => {
    const j = jobOf("T", "t", "@agent-fast-medium", story, NOW);
    expect(j.trail.map((v) => `${v.phase}${v.round}`)).toEqual(["build1", "qa1", "build2", "deliver2"]);
    expect(j.trail[1].v).toEqual({ security: "CHANGES", ux: "PASS", ui: "PASS", code: "PASS" });
    expect(j).toMatchObject({ phase: "deliver", round: 2, step: 0, mins: 5, tier: "fast" });
    expect(j.trail.map((v) => v.mins)).toEqual([40, 5, 10, 5]);
  });

  it("draws the approved board: the phases, the entries from the Board and the exits back to it, and the replay control", () => {
    const s = sceneOf([jobOf("T", "t", undefined, [], NOW)], view("T"), () => {}, NOW);
    expect(texts(s)).toEqual(expect.arrayContaining(["Build", "Deliver", "Review fix"]));
    expect(Object.keys(s.main.tips)).toEqual(expect.arrayContaining(["entry:Ready", "exit:Review"]));
    expect(s.main.H.map((h) => h.aria)).toContain("Play replay");
  });

  it("draws one row per lens once the task has had a QA round", () => {
    const s = sceneOf([jobOf("T", "t", undefined, story, NOW)], view("T"), () => {}, NOW);
    expect(texts(s)).toEqual(expect.arrayContaining(["Security lens", "UX lens", "UI lens", "Code lens"]));
  });

  it("replays the task as it was: 30 minutes back it was still in its first Build", () => {
    expect(jobAt(jobOf("T", "t", undefined, story, NOW), 30)).toMatchObject({ phase: "build", round: 1 });
  });

  it("hands a pick on a hover target back as a view change", () => {
    const changes: Partial<View>[] = [];
    const s = sceneOf([jobOf("T", "t", undefined, [], NOW)], view("T"), (p) => changes.push(p), NOW);
    s.main.V.find((v) => v.aria === "From Ready")!.enter();
    expect(changes).toEqual([{ hover: "entry:Ready" }]);
  });

  it("styles the tooltip and each fleet bar with the theme's tokens, so a theme change repaints them with no redraw", () => {
    const s = sceneOf([jobOf("T", "t", undefined, [], NOW)], { ...view("T"), hover: "entry:Ready" }, () => {}, NOW);
    const colours = (style: string) => style.match(/#[0-9a-fA-F]{3,8}\b|rgba?\(/g);

    expect(s.tip?.style).toContain("var(--bg1)");
    expect(s.tip?.style).toContain("color:var(--ink)");
    expect(s.tip?.style).toContain("var(--slate)");
    expect(colours(s.tip?.style ?? "")).toBeNull();
    expect(s.fleet[0].bar).toContain("color-mix(in srgb, var(--slate) 12%, transparent)");
  });
});
