import { describe, expect, it } from "vitest";
import { LENS_IDS, sunsBoard, type SunsInput } from "./sunsBoard";

const lens = (id: string, state: string) => ({ id, name: id, states: ["pending", "running", "pass"], state, rounds: 2, round: 2 });
const input = (over: Partial<SunsInput> = {}): SunsInput => ({
  task: { id: "TASK-1", profile: "@agent-standard-high" },
  phase: "qa",
  phases: [
    { id: "build", name: "Build", state: "done", rounds: 1, round: 1 },
    { id: "deliver", name: "Deliver", state: "ci-validate", rounds: 3, round: 2 },
    { id: "review_fix", name: "Review fix", state: "idle", rounds: 1, round: 1 },
  ],
  lenses: LENS_IDS.map((id) => lens(id, "running")),
  entries: ["Ready", "Review"],
  exits: ["Needs Attention", "Done"],
  ...over,
});

describe("sunsBoard", () => {
  it("draws Build, the four lenses (forked and joined), Deliver and Review fix as suns", () => {
    const b = sunsBoard(input());
    expect(b.suns.map((s) => s.id)).toEqual(["build", ...LENS_IDS, "deliver", "review_fix"]);
    expect(b.dots.map((d) => d.id)).toEqual(["fork", "join"]);
  });

  it("keeps one folded row per machine: current state named, r1..rN pills, no expand marker", () => {
    const b = sunsBoard(input());
    expect(b.rows).toHaveLength(7);
    const deliver = b.rows.find((r) => r.id === "deliver")!;
    expect(deliver.state).toBe("ci-validate");
    expect(deliver.pills.map((p) => p.label)).toEqual(["r1", "r2", "r3"]);
    expect(deliver.pills.map((p) => p.current)).toEqual([false, true, false]);
    expect(Object.keys(deliver)).not.toContain("expanded");
  });

  it("groups rows Build | lenses | Deliver | Review fix and separates groups only", () => {
    const b = sunsBoard(input());
    expect(b.groups.map((g) => g.rows)).toEqual([["build"], [...LENS_IDS], ["deliver"], ["review_fix"]]);
    expect(b.separators).toHaveLength(3);
    for (const [i, s] of b.separators.entries()) {
      const above = b.rows.find((r) => r.id === b.groups[i].rows.at(-1))!;
      const below = b.rows.find((r) => r.id === b.groups[i + 1].rows[0])!;
      expect(s.y).toBeGreaterThan(above.y);
      expect(s.y).toBeLessThan(below.y);
    }
  });

  it("puts one routing track beside the pills and runs every stem into it along the row's hairline", () => {
    const b = sunsBoard(input());
    expect(b.track.x).toBeGreaterThan(Math.max(...b.rows.flatMap((r) => r.pills.map((p) => p.x))));
    expect(b.stems).toHaveLength(b.rows.length);
    for (const r of b.rows) {
      const s = b.stems.find((x) => x.row === r.id)!;
      expect(s.points[0].y).toBe(r.y);
      expect(s.points.at(-1)!.x).toBe(b.track.x);
    }
    const arcs = new Set(b.stems.map((s) => s.arc));
    expect(arcs.size).toBe(1);
  });

  it("enters flows at the left edge and leaves them at the right edge, named above their lines", () => {
    const b = sunsBoard(input());
    expect(b.entries.every((e) => e.line.x0 === 0)).toBe(true);
    expect(b.exits.every((e) => e.line.x1 === b.width)).toBe(true);
    for (const f of [...b.entries, ...b.exits]) expect(f.label.y).toBeLessThan(f.line.y);
  });

  it("sits an exit label left of its arrowhead without touching it", () => {
    const b = sunsBoard(input());
    for (const e of b.exits) expect(e.label.x + e.label.w).toBeLessThan(e.line.x1 - e.arrow);
  });

  it("never lets a label cross a line", () => {
    const b = sunsBoard(input());
    const lines = [...b.entries, ...b.exits].map((f) => f.line);
    for (const f of [...b.entries, ...b.exits]) {
      const l = f.label;
      for (const ln of lines) {
        const overlapX = l.x < ln.x1 && l.x + l.w > ln.x0, overlapY = l.y - l.h < ln.y && l.y > ln.y;
        expect(overlapX && overlapY, `${f.label.text} crosses a line`).toBe(false);
      }
    }
  });

  it("draws exits as lines, never board states, with the two Deliver exits as non-crossing flat curves", () => {
    const b = sunsBoard(input());
    expect(b.suns.map((s) => s.id)).not.toContain("done");
    const [attention, done] = b.exits;
    const deliver = b.rows.find((r) => r.id === "deliver")!;
    expect(attention.line.y).toBeLessThan(deliver.y);
    expect(done.line.y).toBeGreaterThan(deliver.y);
    expect(done.join).toEqual(attention.join);
  });

  it("centres lens names above their suns", () => {
    const b = sunsBoard(input());
    for (const s of b.suns.filter((x) => LENS_IDS.includes(x.id))) {
      expect(s.label.x).toBe(s.x);
      expect(s.label.y).toBeLessThan(s.y - s.r);
    }
  });

  it("colours the arrival ring with the task's tier colour, never amber, and has no yellow anywhere", () => {
    const b = sunsBoard(input());
    expect(b.task.color).toBe("#67e8f9");
    expect(b.task.ring).toBe(b.task.color);
    const colours = JSON.stringify(b).toLowerCase();
    for (const amber of ["#fbbf24", "#fcd34d", "#eab308", "#facc15"]) expect(colours).not.toContain(amber);
  });

  it("gives a person or fast task a non-yellow colour", () => {
    expect(sunsBoard(input({ task: { id: "TASK-2", profile: "@adin" } })).task.color).not.toBe("#fde68a");
  });

  it("is static: the same input gives the same layout and nothing carries a motion", () => {
    expect(sunsBoard(input())).toEqual(sunsBoard(input()));
  });
});
