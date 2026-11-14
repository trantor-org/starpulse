// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SpendPhase } from "../../api";
import { SpendRail, SpendRows, compactWte, fetchSpend, forgetSpend, phasesOf } from "./spend";

const phase = (over: Partial<SpendPhase>): SpendPhase => ({
  task: "TASK-1", phase: "implement", steps: 3, side_steps: 0, input: 0, output: 0, cache_read: 0, cache_write: 0, wte: 1000,
  peak_context: 0, compactions: 0, models: ["claude-sonnet-5-5"], first_at: 0, last_at: 0, kind: "execute", size: 3,
  task_wte: 2500, norm_wte: null, above_norm: false, phase_norm_wte: null, phase_above_norm: false, ...over,
});
const answer = (spend: SpendPhase[]) => vi.fn(async () => ({ ok: true, json: async () => ({ spend }) }) as unknown as Response);

const mounted: { root: ReturnType<typeof createRoot>; host: HTMLElement }[] = [];
/** The text the element draws once React has run its effects. */
async function draw(ui: React.ReactElement): Promise<string> {
  const host = document.body.appendChild(document.createElement("div"));
  const root = createRoot(host);
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  await act(async () => root.render(ui));
  mounted.push({ root, host });
  return host.textContent ?? "";
}
beforeEach(forgetSpend);
afterEach(() => {
  for (const { root, host } of mounted.splice(0)) { act(() => root.unmount()); host.remove(); }
  vi.unstubAllGlobals();
});

describe("spend", () => {
  it("compacts weighted tokens", () => {
    expect([812, 4200, 130_000, 1_300_000].map(compactWte)).toEqual(["812", "4.2K", "130K", "1.3M"]);
  });

  it("keeps one task's phases in lifecycle order", () => {
    const rows = [phase({ phase: "deliver" }), phase({ task: "TASK-2" }), phase({ phase: "claim" })];
    expect(phasesOf(rows, "TASK-1").map((r) => r.phase)).toEqual(["claim", "deliver"]);
  });

  it("asks the server once a minute, and again after a few seconds when it failed", async () => {
    const fetcher = answer([phase({})]);
    await fetchSpend(fetcher, 0);
    await fetchSpend(fetcher, 30_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    forgetSpend();
    expect(await fetchSpend(vi.fn(async () => ({ ok: false }) as Response), 0)).toBeNull();
    forgetSpend();
    expect(await fetchSpend(vi.fn(async () => { throw new Error("down"); }), 0)).toBeNull();
    const retry = answer([phase({})]);
    expect(await fetchSpend(retry, 1_000)).toBeNull();
    expect(await fetchSpend(retry, 6_000)).toHaveLength(1);
  });

  it("flags a task far above its norm and names each phase with its steps, compactions and models", async () => {
    const text = await draw(<SpendRows rows={[
      phase({ phase: "claim", wte: 150, steps: 1, task_wte: 90_000, norm_wte: 20_000, above_norm: true }),
      phase({ phase: "implement", wte: 89_850, compactions: 2, task_wte: 90_000, norm_wte: 20_000, above_norm: true }),
    ]} />);
    expect(text).toContain("90.0K WTE");
    expect(text).toContain("4.5× norm (20.0K)");
    expect(text).toContain("1 step");
    expect(text).toContain("3 steps · 2 compactions · sonnet-5-5");
  });

  it("shows the norm without a flag under 3x, and an empty state for a task with no spend", async () => {
    const near = await draw(<SpendRows rows={[phase({ norm_wte: 2000 })]} />);
    expect(near).not.toContain("× norm");
    expect(near).toContain("norm 2.0K");
    vi.stubGlobal("fetch", answer([phase({ task: "TASK-9" })]));
    expect(await draw(<SpendRail task="TASK-1" />)).toContain("No spend recorded in the last 7 days");
    forgetSpend();
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false }) as Response));
    expect(await draw(<SpendRail task="TASK-1" />)).toContain("Spend unavailable");
  });
});
