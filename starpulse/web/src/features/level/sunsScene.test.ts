// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MachineEvent } from "../../api/types.gen";
import { applyPack, applyTheme, packTokens } from "../../tests/themeFixtures";
import { jobAt, statusOf, TIER } from "./sunsEngine";
import { css, jobOf, sceneOf, stepOut, type View } from "./sunsScene";

const NOW = 1_800_000_000;
const ev = (ago: number, machine: string, from: string, to: string, event = "E"): MachineEvent => ({ at: NOW - ago * 60, machine, event, from, to });
const lens = (ago: number, event: string, from: string, to: string) => ev(ago, "qa", from, to, event);
const view = (sel: string): View => ({ sel, open: {}, pick: {}, hover: null, det: null, at: null, replaying: false });
const texts = (s: ReturnType<typeof sceneOf>) => [...s.main.T, ...s.rows.T].map((t) => t.text);

// Build for 40 minutes, the qa machine's five lenses (Security asks for changes), the fix as Build round 2, then Deliver for the last 5 minutes.
const story = [
  ev(60, "build", "start", "worktree_ready"),
  lens(20, "LENS_CHANGED", "security", "ux_dirty"), lens(19, "LENS_PASSED", "ux_dirty", "ui_dirty"), lens(18, "LENS_PASSED", "ui_dirty", "code_dirty"),
  lens(17, "LENS_PASSED", "code_dirty", "simplify_dirty"), lens(16, "LENS_PASSED", "simplify_dirty", "fixing"),
  lens(15, "CHANGES_FIXED", "fixing", "security"),
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
    expect(j.trail[1].v).toEqual({ security: "CHANGES", ux: "PASS", ui: "PASS", code: "PASS", simplify: "PASS" });
    expect(j).toMatchObject({ phase: "deliver", round: 2, step: 0, mins: 5, tier: "fast" });
    expect(j.trail.map((v) => v.mins)).toEqual([40, 5, 10, 5]);
  });

  it("reads the live qa lens states: a timeout is CHANGES, and the live round carries each lens", () => {
    const j = jobOf("T", "t", undefined, [lens(9, "LENS_PASSED", "security", "ux"), lens(8, "LENS_TIMED_OUT", "ux", "ui_dirty")], NOW);
    expect(j).toMatchObject({ phase: "qa", round: 1, lenses: { security: { state: "PASS" }, ux: { state: "CHANGES" } } });
  });

  it("shows the lens under review as live and the lenses still to come as queued, and counts the reported ones", () => {
    const j = jobOf("T", "t", undefined, [lens(9, "LENS_PASSED", "security", "ux")], NOW);
    expect(j.lenses).toEqual({
      security: { state: "PASS", step: 3 }, ux: { state: "pending", step: 1 },
      ui: { state: "pending", step: 0 }, code: { state: "pending", step: 0 }, simplify: { state: "pending", step: 0 },
    });
    expect(statusOf(j).t).toBe("QA 1/5");
  });

  it("draws the approved board: the phases, the entries from the Board and the exits back to it, and the replay control", () => {
    const s = sceneOf([jobOf("T", "t", undefined, [], NOW)], view("T"), () => {}, NOW);
    expect(texts(s)).toEqual(expect.arrayContaining(["Build", "Deliver", "Review fix"]));
    expect(Object.keys(s.main.tips)).toEqual(expect.arrayContaining(["entry:Ready", "exit:Review"]));
    expect(s.main.H.map((h) => h.aria)).toContain("Play replay");
  });

  it("draws one row per lens once the task has had a QA round", () => {
    const s = sceneOf([jobOf("T", "t", undefined, story, NOW)], view("T"), () => {}, NOW);
    expect(texts(s)).toEqual(expect.arrayContaining(["Security lens", "UX lens", "UI lens", "Code lens", "Simplify lens"]));
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

  describe("theme", () => {
    afterEach(() => void applyPack("starpulse"));
    const hexes = (v: unknown) => JSON.stringify(v).match(/#[0-9a-f]{6}\b/gi) ?? [];
    const drawn = () => {
      const jobs = [jobOf("T", "t", "@agent-deep-high", story, NOW), jobOf("U", "u", undefined, [], NOW), jobOf("V", "v", "@agent-fast-medium", [], NOW)];
      return sceneOf(jobs, { ...view("T"), hover: "entry:Ready" }, () => {}, NOW);
    };

    it("draws the scene in the applied pack's colours, so a pack switch repaints it with no reload", () => {
      const starpulse = packTokens("starpulse"), stub = { ...starpulse, agent: "#123456", waits: "#654321", ok: "#0a0b0c" };
      applyTheme(stub);

      expect(TIER).toMatchObject({ deep: "#123456", standard: "#654321" });
      const found = hexes(drawn());
      expect(found).toContain("#123456");
      expect(found).toContain("#654321");
      expect(found).toContain("#0a0b0c");
      expect(found).not.toContain(starpulse.agent);
      expect(found).not.toContain(starpulse.waits);
    });

    it("draws no colour of the StarPulse pack under another pack", () => {
      const starpulse = new Set(Object.values(packTokens("starpulse"))), nord = new Set(Object.values(applyPack("nord")));
      const foreign = hexes(drawn()).filter((h) => starpulse.has(h.toLowerCase()) && !nord.has(h.toLowerCase()));

      expect(foreign).toEqual([]);
    });
  });

  describe("reflow", () => {
    const at = (w: number, h = 900) => sceneOf([jobOf("T", "t", undefined, story, NOW)], view("T"), () => {}, NOW, { w, h });
    const left = (s: ReturnType<typeof sceneOf>, text: string) => Number(/left:(-?[\d.]+)px/.exec([...s.main.T, ...s.main.K].find((t) => t.text === text)!.style)![1]);
    const top = (s: ReturnType<typeof sceneOf>, aria: string) => Number(/top:(-?[\d.]+)px/.exec([...s.main.H, ...s.main.Q, ...s.main.V].find((b) => b.aria === aria)!.style)![1]);

    it("lays the phase graph out from the container width: nodes follow it, the gutter and the exit edge keep their sides", () => {
      const narrow = at(940), wide = at(1500);

      expect(left(wide, "Deliver")).toBeGreaterThan(left(narrow, "Deliver") + 100);
      expect(left(wide, "Review fix")).toBeGreaterThan(left(narrow, "Review fix") + 100);
      expect(left(wide, "Build")).toBe(left(narrow, "Build"));
      expect(wide.paths.lane).not.toBe(narrow.paths.lane);
    });

    it("draws the rows' rules to the container's right edge at any width, shifted once", () => {
      const rightOf = (s: ReturnType<typeof sceneOf>) => Math.max(...[...s.rpaths.lane.matchAll(/L(-?[\d.]+),/g)].map((m) => Number(m[1])));

      expect(rightOf(at(939))).toBe(1180);
      expect(rightOf(at(1500))).toBe(1180 + 561);
      expect(rightOf(at(800))).toBe(1180 - 139);
    });

    it("anchors the replay bar to the container's bottom edge and gives the rows the height between", () => {
      const tall = at(1200, 1300), short = at(1200, 900);

      expect(top(tall, "Play replay") - top(short, "Play replay")).toBe(400);
      expect(-tall.rowsTop + tall.rowsViewH - (-short.rowsTop + short.rowsViewH)).toBe(400);
    });

    it("stretches the board down a container taller than its content, so the graph and the rows reach the replay bar with no empty band", () => {
      const tall = at(1200, 1300), short = at(1200, 900);
      const labelTop = (s: ReturnType<typeof sceneOf>, text: string) => Number(/top:(-?[\d.]+)px/.exec(s.main.T.find((t) => t.text === text)!.style)![1]);

      expect(labelTop(tall, "Deliver")).toBeGreaterThan(labelTop(short, "Deliver") + 40);
      expect(-tall.rowsTop).toBeGreaterThan(-short.rowsTop + 40);
      expect(tall.rowsH).toBeCloseTo(1300 - 70, 0);
      expect(-tall.rowsTop + tall.rowsViewH).toBe(1300 - 70);
    });
  });
});

describe("stepping out of the drill-in", () => {
  it("unwinds the innermost open level first: a detail, then a replay or scrub, then opened groups, then picked variants, and at the top hands the step to the Board", () => {
    const top = view("TASK-1");
    const all: View = { ...top, det: "lens:ux", at: 30, replaying: true, open: { build: true }, pick: { lens: "ux" } };

    expect(stepOut(all)).toEqual({ det: null });
    expect(stepOut({ ...all, det: null })).toEqual({ at: null, replaying: false });
    expect(stepOut({ ...all, det: null, at: null, replaying: false })).toEqual({ open: {} });
    expect(stepOut({ ...top, open: { build: false }, pick: { lens: "ux" } })).toEqual({ pick: {} });
    expect(stepOut(top)).toBeNull();
  });
});

describe("the tasks at work", () => {
  const orbiters = (s: ReturnType<typeof sceneOf>) => s.main.D;
  const centre = (style: string) => {
    const n = (k: string) => Number(new RegExp(`(?:^|;)${k}:(-?[\\d.]+)px`).exec(style)![1]);
    return `${Math.round(n("left") + n("width") / 2)},${Math.round(n("top") + n("height") / 2)}`;
  };

  it("draws every working task as a dot beside the phase it is in, a task in QA on each lens still reviewing it, so several tasks in several phases all show at once", () => {
    const jobs = [
      jobOf("B1", "b1", "@agent-deep-high", [], NOW),
      jobOf("B2", "b2", undefined, [], NOW),
      jobOf("D1", "d1", undefined, [ev(5, "in-progress", "build", "deliver")], NOW),
      jobOf("R1", "r1", undefined, [ev(5, "in-progress", "deliver", "review_fix")], NOW),
      jobOf("Q1", "q1", undefined, [lens(9, "LENS_PASSED", "security", "ux")], NOW),
    ];
    const s = sceneOf(jobs, view("B1"), () => {}, NOW);
    const dots = orbiters(s);
    const suns = new Map<string, number>();
    for (const d of dots) suns.set(centre(d.style), (suns.get(centre(d.style)) ?? 0) + 1);
    const perSun = [...suns.values()].sort();

    // build holds two, deliver and review fix one each, and the QA task rides the four lenses that have not passed it yet
    expect(perSun).toEqual([1, 1, 1, 1, 1, 1, 2]);
    // the picked task's dot is the larger one
    const sizes = dots.map((d) => Number(/width:([\d.]+)px/.exec(d.style)![1]));
    expect(sizes.filter((w) => w === Math.max(...sizes))).toHaveLength(1);
  });

  it("keeps each dot still at its own place round the sun, so two tasks on one sun never stack and only a real move stirs one", () => {
    const s = sceneOf([jobOf("B1", "b1", undefined, [], NOW), jobOf("B2", "b2", undefined, [], NOW)], view("B1"), () => {}, NOW);
    const places = orbiters(s).map((d) => /transform:translate\([^)]+\)/.exec(d.style)![0]);

    expect(new Set(places).size).toBe(2);
    orbiters(s).forEach((d) => expect(d.style).not.toContain("animation"));
  });

  it("keeps a resting dot off the sun's name: below a phase's sun its name, above a lens's", () => {
    const places = (jobs: ReturnType<typeof jobOf>[]) =>
      orbiters(sceneOf(jobs, view(jobs[0].id), () => {}, NOW)).map((d) => /translate\(([-\d.]+)px,([-\d.]+)px\)/.exec(d.style)!.slice(1).map(Number));

    for (const n of [1, 2, 3, 4, 5, 8]) {
      const building = places(Array.from({ length: n }, (_, i) => jobOf(`B${i}`, "b", undefined, [], NOW)));
      const reviewing = places(Array.from({ length: n }, (_, i) => jobOf(`Q${i}`, "q", undefined, [lens(9, "LENS_PASSED", "security", "ux"), lens(9, "LENS_PASSED", "ux", "ui"), lens(9, "LENS_PASSED", "ui", "code"), lens(9, "LENS_PASSED", "code", "simplify")], NOW)));

      expect(Math.max(...building.map(([, dy]) => dy))).toBeLessThanOrEqual(10);
      expect(Math.min(...reviewing.map(([, dy]) => dy))).toBeGreaterThanOrEqual(-9);
      expect(new Set(building.map(String)).size).toBe(n);
    }
  });

  it("flies a task's dot to the phase it enters: the dot keeps its key and eases to the new sun", () => {
    const dot = (events: Parameters<typeof jobOf>[3]) => orbiters(sceneOf([jobOf("F1", "f1", undefined, events, NOW)], view("F1"), () => {}, NOW))[0];
    const inBuild = dot([]), inDeliver = dot([ev(5, "in-progress", "build", "deliver")]);

    expect(inDeliver.key).toBe(inBuild.key);
    expect(centre(inDeliver.style)).not.toBe(centre(inBuild.style));
    expect(inDeliver.style).toMatch(/transition:left [^;]*top [^;]*transform /);
  });

  it("keeps the key of a QA task's dot on a lens when an earlier lens passes it, so the other dots stay put", () => {
    const keyed = (events: Parameters<typeof jobOf>[3]) => new Map(orbiters(sceneOf([jobOf("Q2", "q2", undefined, events, NOW)], view("Q2"), () => {}, NOW)).map((d) => [d.key, centre(d.style)]));
    const before = keyed([lens(9, "LENS_PASSED", "security", "ux")]), after = keyed([lens(9, "LENS_PASSED", "security", "ux"), lens(10, "LENS_PASSED", "ux", "ui")]);

    expect(after.size).toBe(before.size - 1);
    for (const [key, at] of after) expect(before.get(key)).toBe(at);
  });
});

describe("a phase machine row", () => {
  afterEach(() => vi.useRealTimers());

  const drawn = (id: string, events: Parameters<typeof jobOf>[3]) => sceneOf([jobOf(id, id, undefined, events, NOW)], view(id), () => {}, NOW).rows;

  describe("with more rounds than fit before the row", () => {
    const events = [6, 5, 4, 3, 2].flatMap((r) => [ev(r * 10 + 5, "in-progress", "build", "deliver"), ev(r * 10, "in-progress", "deliver", "build")]);
    const roundsIn = (v: View) => sceneOf([jobOf("P1", "p1", undefined, events, NOW)], v, () => {}, NOW).rows.Q;
    const numbers = (q: ReturnType<typeof roundsIn>) => q.flatMap((b) => /^build round (\d+)$/.exec(b.aria)?.[1] ?? []).map(Number);

    it("draws three pills at most, the newest round lit, and says how many older rounds it holds back", () => {
      const q = roundsIn(view("P1")).filter((b) => b.aria.startsWith("build "));

      expect(q).toHaveLength(3);
      expect(numbers(q)).toEqual([5, 6]);
      expect(q[0].text).toBe("\u2039" + "3");
    });

    it("reaches every older round from the held-back pill, one round per click, and comes back by its newer pill", () => {
      const seen = new Set<number>();
      let v = view("P1");
      for (let i = 0; i < 6; i++) {
        const q = roundsIn(v).filter((b) => b.aria.startsWith("build "));
        numbers(q).forEach((n) => seen.add(n));
        expect(q.length).toBeLessThanOrEqual(3);
        const older = q.find((b) => b.aria.includes("older"));
        if (!older) break;
        const set = vi.fn();
        sceneOf([jobOf("P1", "p1", undefined, events, NOW)], v, set, NOW).rows.Q.find((b) => b.aria === older.aria)!.pick();
        v = { ...v, ...set.mock.calls[0][0] };
      }

      expect([...seen].sort()).toEqual([2, 3, 4, 5, 6]);
      const set = vi.fn();
      sceneOf([jobOf("P1", "p1", undefined, events, NOW)], v, set, NOW).rows.Q.find((b) => b.aria === "build round 3")!.pick();
      expect(numbers(roundsIn({ ...v, ...set.mock.calls[0][0] }).filter((b) => b.aria.startsWith("build ")))).toContain(4);
    });

    it("draws every round when they fit", () => {
      const three = [5, 4, 3].flatMap((r) => [ev(r * 10 + 5, "in-progress", "build", "deliver"), ev(r * 10, "in-progress", "deliver", "build")]);
      const q = sceneOf([jobOf("P2", "p2", undefined, three, NOW)], view("P2"), () => {}, NOW).rows.Q.filter((b) => b.aria.startsWith("build "));

      expect(numbers(q)).toEqual([2, 3, 4]);
      expect(q).toHaveLength(3);
    });
  });

  it("leaves the task's dot where it is from one draw to the next while the task rests", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000_000);
    const first = drawn("R2", []).S.map((x) => x.style);

    vi.advanceTimersByTime(60_000);

    expect(drawn("R2", []).S.map((x) => x.style)).toEqual(first);
  });

  it("marks a comet's pieces apart, so one coming and going shifts no piece that stays", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000_000_000);
    const walked = [ev(5, "build", "start", "worktree_ready")], moved = [...walked, ev(4, "build", "worktree_ready", "red_proven")];
    drawn("C2", walked);

    vi.advanceTimersByTime(100);
    const flying = drawn("C2", moved);
    vi.advanceTimersByTime(60_000);
    const landed = drawn("C2", moved);

    expect(flying.L.some((l) => l.fx)).toBe(true);
    expect(landed.L.some((l) => l.fx)).toBe(false);
    expect(flying.L.filter((l) => !l.fx).map((l) => l.d)).toEqual(landed.L.filter((l) => !l.fx).map((l) => l.d));
    expect(flying.S.filter((b) => !b.fx).map((b) => b.style)).toEqual(landed.S.filter((b) => !b.fx).map((b) => b.style));
  });
});
