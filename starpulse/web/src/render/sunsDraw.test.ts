import { describe, expect, it } from "vitest";
import { LENS_IDS, sunsBoard, type SunsInput } from "../features/level/sunsBoard";
import { drawSuns, type Travel } from "./sunsDraw";
import { TRAVEL, PULSE } from "./sky";

const input: SunsInput = {
  task: { id: "TASK-1", profile: "@agent-standard-high" },
  phase: "deliver",
  phases: [
    { id: "build", name: "Build", state: "done", rounds: 1, round: 1 },
    { id: "deliver", name: "Deliver", state: "ci-validate", rounds: 2, round: 2 },
    { id: "review_fix", name: "Review fix", state: "idle", rounds: 1, round: 1 },
  ],
  lenses: LENS_IDS.map((id) => ({ id, name: id, states: ["pending", "pass"], state: "pass", rounds: 1, round: 1 })),
  entries: ["Ready"],
  exits: ["Needs Attention", "Done"],
};
const board = sunsBoard(input);

// A canvas that records what the drawing does: every call and every assigned property.
const recorder = () => {
  const calls: [string, unknown[]][] = [], colours: string[] = [];
  const grad = { addColorStop: (_o: number, c: string) => void colours.push(c) };
  const cx = new Proxy({} as Record<string, unknown>, {
    get: (t, k: string) =>
      k in t ? t[k] : k === "measureText" ? (s: string) => ({ width: s.length * 6 })
        : (...a: unknown[]) => (calls.push([k, a]), k.startsWith("create") ? grad : undefined),
    set: (t, k: string, v) => ((t[k] = v), ["fillStyle", "strokeStyle"].includes(k) && typeof v === "string" && colours.push(v), calls.push([`set ${k}`, [v]]), true),
  }) as unknown as CanvasRenderingContext2D;
  return { cx, calls, colours };
};
const frame = (clock: number, now: number, travel?: Travel) => {
  const r = recorder();
  drawSuns({ cx: r.cx, K: 1, ZS: 1, clock, scale: 1, hover: null }, board, { now, travel });
  return r;
};
const AMBER = ["251,191,36", "253,230,138", "252,211,77", "234,179,8", "250,204,21"];

describe("drawSuns", () => {
  it("names every sun, its current state and its round pills", () => {
    const text = frame(0, 0).calls.filter(([k]) => k === "fillText").map(([, a]) => a[0]);
    for (const w of ["Build", "security", "Deliver", "Review fix", "ci-validate", "r1", "r2", "Ready", "Needs Attention", "Done"]) expect(text).toContain(w);
  });

  it("moves nothing on load: labels and pills sit in the same place at any clock, and no comet or ring is drawn", () => {
    const at = (c: number) => frame(c, 0).calls.filter(([k]) => k === "fillText");
    expect(at(0)).toEqual(at(41.7));
    expect(frame(5, 0).calls.some(([k, a]) => k === "set globalCompositeOperation" && a[0] === "lighter")).toBe(false);
  });

  it("flies the task as a comet for TRAVEL seconds after a real transition, then rings it for PULSE", () => {
    const travel: Travel = { from: board.dots[0], to: board.suns.find((s) => s.id === "deliver")!, at: 10 };
    const lighter = (r: ReturnType<typeof frame>) => r.calls.some(([k, a]) => k === "set globalCompositeOperation" && a[0] === "lighter");
    expect(lighter(frame(0, 10 + TRAVEL / 2, travel))).toBe(true);
    expect(lighter(frame(0, 10 + TRAVEL + 0.1, travel))).toBe(false);
    const ringing = frame(0, 10 + TRAVEL + PULSE / 2, travel).calls.filter(([k]) => k === "arc").length;
    expect(ringing).toBeGreaterThan(frame(0, 10 + TRAVEL + PULSE + 1, travel).calls.filter(([k]) => k === "arc").length);
  });

  it("cuts the row line out behind each state label and round pill, so no text sits on a flow line", () => {
    const cuts = frame(0, 5).calls.filter(([k]) => k === "clearRect").length;
    const pills = board.rows.reduce((n, r) => n + r.pills.length, 0);
    expect(cuts).toBe(board.rows.length + pills);
  });

  it("uses the task's own colour and no amber or yellow in any state of the animation", () => {
    const travel: Travel = { from: board.dots[0], to: board.suns[5], at: 0 };
    for (const now of [0, TRAVEL / 2, TRAVEL + PULSE / 2, 60]) {
      const all = frame(3, now, travel).colours.join(" ");
      for (const a of AMBER) expect(all, `amber at ${now}s`).not.toContain(a);
    }
    expect(frame(0, TRAVEL / 2, travel).colours.join(" ")).toContain("103,232,249"); // #67e8f9, the standard tier
  });
});
