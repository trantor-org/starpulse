import { describe, expect, it } from "vitest";
import history from "./fixtures/history-phase-skill.json";
import { trailOf } from "./traceDraw";
import type { RouteOf } from "./transit";
import type { MachineStep } from "../features/level/trace";

const HUB = "#ffffff", BLUE = "#0000ff", TEAL = "#00ff00";
type N = RouteOf["run"][number];
const hub = (b: string, c = HUB): N => ({ k: `${b}:h`, x: 0, y: 0, c, machine: "" });
/** A machine's stations in step order, a sample before each: x runs on from `x0`. */
const leg = (b: string, machine: string, steps: string[], c: string, x0: number): N[] =>
  steps.flatMap((step, i): N[] => [
    { k: `${b}:s${i}`, x: x0 + i * 20 - 10, y: 0, c, machine },
    { k: `${b}:${i}`, x: x0 + i * 20, y: 0, c, machine, step },
  ]);
const route = (run: N[]): RouteOf => ({ run, end: { x: run.at(-1)!.x + 5, y: 0, c: run.at(-1)!.c, machine: run.at(-1)!.machine } });
const path = (...states: string[]): MachineStep[] => states.map((state, i) => ({ at: 100 + i, event: "E", state }));

describe("trailOf", () => {
  const build = leg("b", "build", ["start", "red", "green"], BLUE, 0);

  it("follows the branch lines machine to machine: hub, the phase's stations, the sub-machine's, then the dot", () => {
    const sub = leg("s", "tdd", ["red", "green"], TEAL, 60);
    const trail = trailOf(route([hub("b"), ...build, ...sub]), { build: path("start", "red", "green"), tdd: path("red", "green") });
    expect(trail.pts.map((p) => p.x)).toEqual([0, -10, 0, 10, 20, 30, 40, 50, 60, 70, 80, 85]);
    expect(trail.machines).toEqual(["build", "tdd"]);
  });

  it("follows a parallel dot's own branch back to its fork and leaves its sibling's out", () => {
    const fork = build.slice(0, 2), mine = leg("m", "deliver", ["pr", "ci"], TEAL, 20), theirs = leg("t", "review_fix", ["threads"], TEAL, 20);
    const trail = trailOf(route([hub("b"), ...fork, ...mine]), {});
    expect(trail.stations.map((s) => s.k)).toEqual(["b:0", "m:0", "m:1"]);
    expect(trail.stations.map((s) => s.k)).not.toContain(theirs[0].k);
    expect(trail.machines).toEqual(["build", "deliver"]);
  });

  it("lights only the stations the history landed in, keeping the fork and the dot's own", () => {
    const sub = leg("s", "tdd", ["red", "green"], TEAL, 60);
    const trail = trailOf(route([hub("b"), ...build, ...sub]), { build: path("start", "green"), tdd: path("green") });
    expect(trail.stations.map((s) => s.k)).toEqual(["b:0", "b:2", "s:1"]);
  });

  it("blends the colour across the stretch between the last station of one machine and the first of the next", () => {
    const sub = leg("s", "tdd", ["red", "green"], TEAL, 60);
    const { pts } = trailOf(route([hub("b"), ...build, ...sub]), {});
    const at = (x: number) => pts.find((p) => p.x === x)!.c;
    expect(at(40)).toBe(BLUE);
    expect(at(60)).toBe(TEAL);
    expect(at(50)).not.toBe(BLUE);
    expect(at(50)).not.toBe(TEAL);
  });

  it("returns the phase machines a live task ran its phase skill through, in the order it walked them", () => {
    const walked = history as unknown as Record<string, MachineStep[]>;
    const run = [hub("r"), ...leg("r", "review_fix", ["start"], BLUE, 0), ...leg("d", "deliver", ["start"], BLUE, 20), ...leg("b", "build", ["start"], BLUE, 40)];
    expect(trailOf(route(run), walked).machines).toEqual(["build", "deliver", "review_fix"]);
  });
});
