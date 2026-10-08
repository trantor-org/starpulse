import { describe, expect, it } from "vitest";
import { demoLevel } from "./demoLevel";

const NOW = 1_800_000_000;
const ask = (query = "", hours = 168) => demoLevel(NOW, hours, new URLSearchParams(query));
const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);

describe("the demo's level", () => {
  it("answers as /api/level does: shares that sum to one, arrivals that are the runs each source ended, oldest first, inside the window", () => {
    const { status, body } = ask();
    expect(status).toBe(200);
    for (const s of body.sources) {
      if (sum(s.ended)) expect(sum(s.terminal_share)).toBeCloseTo(1, 9);
      expect(sum(s.time_share)).toBeCloseTo(1, 9);
      expect(body.arrivals.filter((a) => a.source === s.id)).toHaveLength(sum(s.ended));
    }
    const at = body.arrivals.map((a) => a.at);
    expect(at).toEqual([...at].sort((a, b) => a - b));
    expect(Math.min(...at)).toBeGreaterThanOrEqual(NOW - body.window_s);
    expect(Math.max(...at)).toBeLessThanOrEqual(NOW);
    for (const [id, t] of Object.entries(body.orbit.terminals)) expect(t.ended).toBe(body.arrivals.filter((a) => a.state === id).length);
  });

  it("has three named sources and the unattributed aggregate, one source drifted from its config", () => {
    const { body } = ask();
    expect(body.sources.filter((s) => s.shared)).toHaveLength(3);
    expect(body.sources.filter((s) => !s.shared).map((s) => s.id)).toEqual(["unattributed"]);
    expect(body.sources.filter((s) => s.drift)).toHaveLength(1);
  });

  it("lists each source's open runs oldest first, some past the aging threshold, adding up to the open count in each state", () => {
    const { body } = ask();
    for (const s of body.sources) expect(body.aging.runs.filter((r) => r.source === s.id)).toHaveLength(s.wip);
    const ages = body.aging.runs.map((r) => r.age_s);
    expect(ages).toEqual([...ages].sort((a, b) => b - a));
    expect(body.aging.runs.every((r) => r.over === r.age_s > body.aging.threshold_s!)).toBe(true);
    expect(body.aging.runs.some((r) => r.over)).toBe(true);
    const open: Record<string, number> = {};
    for (const r of body.aging.runs) open[r.state] = (open[r.state] ?? 0) + 1;
    expect(body.wip.states).toEqual(open);
    expect(sum(body.wip.states)).toBe(body.wip.count);
  });

  it("gives every working state its stays and mean, from the sources' time there", () => {
    const { body } = ask();
    expect(body.time_in_state.map((t) => t.id)).toEqual(body.level.orbit.working);
    for (const t of body.time_in_state) {
      expect(t.task_s).toBe(body.orbit.working[t.id].task_s);
      expect(t.mean_s).toBeCloseTo(t.task_s / t.visits, 6);
    }
  });

  it("draws the suns the page's address names, terminals unless ?suns=working, each from the same config", () => {
    expect(ask().body.level.orbit.suns).toBe("terminal");
    const w = ask("suns=working").body;
    expect([w.level.orbit.suns, w.orbit.suns]).toEqual(["working", "working"]);
    expect(w.level.terminals.length).toBeGreaterThan(1);
  });

  it("refuses as the OIDC gate does when the address asks it to", () => {
    expect(ask("gate=expired")).toMatchObject({ status: 401 });
    expect(ask("gate=refused")).toMatchObject({ status: 403, body: { error: expect.stringContaining("team") } });
  });

  it("refuses a window longer than its history with the history's length, as the server does", () => {
    expect(ask("", 24 * 60)).toMatchObject({ status: 400, body: { history_s: 30 * 86400 } });
  });
});
