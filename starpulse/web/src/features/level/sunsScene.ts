// The bridge between the board and the ported B · Suns engine: a task's 24h of machine events become the engine's job (its visits to Build, QA,
// Deliver and Review fix, rounds and steps), and one pass of the engine becomes the scene, tooltips, details and Tasks panel the drill-in draws.
import type { CSSProperties } from "react";
import type { MachineEvent } from "../../api/types.gen";
import { tint } from "./tint";
import { HAIR, jobAt, LENSES, LN, PANE_R, PN, replay, rows, setNowMinutes, statusOf, STEPS, STYLE, template, TIER, type Job, type Scene, type View } from "./sunsEngine";

export type { Job, View };

/** The engine's inline style strings as React style properties; a declaration's value may hold `;` only inside parentheses. */
export function css(s: string): CSSProperties {
  const out: Record<string, string> = {};
  let depth = 0, start = 0;
  const take = (end: number) => {
    const decl = s.slice(start, end), colon = decl.indexOf(":");
    start = end + 1;
    if (colon < 0) return;
    const key = decl.slice(0, colon).trim();
    out[key.startsWith("--") ? key : key.replace(/^-/, "").replace(/-([a-z])/g, (_, c: string) => c.toUpperCase()).replace(/^(webkit|moz|ms)/, (p) => p[0].toUpperCase() + p.slice(1))] = decl.slice(colon + 1).trim();
  };
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "(") depth++;
    else if (s[i] === ")") depth--;
    else if (s[i] === ";" && depth === 0) take(i);
  }
  take(s.length);
  return out;
}

/** The in-progress machine's states as the engine's phases. */
const PHASE_OF: Record<string, string> = { build: "build", qa: "qa", deliver: "deliver", review_fix: "review_fix", needs_attention: "parked", parked: "parked", review_recorded: "done", finalized: "done" };
/** The qa machine's verdict events: a lens that times out has asked for changes. */
const VERDICT: Record<string, string> = { LENS_PASSED: "PASS", LENS_CHANGED: "CHANGES", LENS_TIMED_OUT: "CHANGES" };
const TIER_OF = /@agent-(deep|standard|fast)-/;

interface Visit {
  phase: string;
  round: number;
  at: number;
  lenses: Record<string, string>;
  /** The lens the qa machine is waiting on, the state after the last verdict. */
  reviewing?: string;
}
const lensOf = (state: string) => state.replace(/_dirty$/, "");

/**
 * The engine's job for a task: one visit per phase it entered, in order. The in-progress machine moves it between phases; a verdict on the qa
 * machine puts it in QA (the lens is the state it left, minus `_dirty`) and its CHANGES_FIXED is the fix in Build; a phase machine's own
 * transition puts it in that phase. Each return to Build starts a round, and the step is the current phase
 * machine's state. With no events the task is at Build's first step, round 1.
 */
export function jobOf(id: string, title: string, assignee: string | undefined, events: MachineEvent[], nowSec: number): Job {
  const visits: Visit[] = [], state: Record<string, string> = {};
  const enter = (phase: string, at: number) => {
    const last = visits.at(-1);
    if (last?.phase === phase) return;
    visits.push({ phase, round: (last?.round ?? 1) + (last && phase === "build" ? 1 : 0), at, lenses: {} });
  };
  for (const e of [...events].sort((a, b) => a.at - b.at)) {
    state[e.machine] = e.to;
    if (e.machine === "in-progress" && PHASE_OF[e.to]) enter(PHASE_OF[e.to], e.at);
    else if (e.machine === "qa") {
      if (e.event === "CHANGES_FIXED") enter("build", e.at);
      else if (VERDICT[e.event]) {
        enter("qa", e.at);
        visits.at(-1)!.lenses[lensOf(e.from)] = VERDICT[e.event];
        visits.at(-1)!.reviewing = lensOf(e.to);
      }
    } else if (STEPS[e.machine] && (e.from !== e.to || !visits.length)) enter(e.machine, e.at);
  }
  if (!visits.length) enter("build", nowSec);

  const verdicts = (v: Visit) => Object.fromEntries(LENSES.filter((l) => v.lenses[l]).map((l) => [l, v.lenses[l]]));
  const trail = visits.map((v, i) => {
    const mins = Math.round(((visits[i + 1]?.at ?? nowSec) - v.at) / 60);
    if (v.phase !== "qa" || i === visits.length - 1) return { phase: v.phase, round: v.round, mins };
    const vs = verdicts(v), bad = LENSES.find((l) => vs[l] === "CHANGES");
    return { phase: v.phase, round: v.round, mins, v: vs, ...(bad ? { why: `${LN[bad]}: a finding to address` } : {}) };
  });
  const cur = visits.at(-1)!, steps = cur.phase === "qa" ? undefined : STEPS[cur.phase];
  const pending = (l: string) => ({ state: "pending", step: l === cur.reviewing ? 1 : 0 });
  const lenses = cur.phase !== "qa" ? {} : Object.fromEntries(LENSES.map((l) => [l, cur.lenses[l] ? { state: cur.lenses[l], step: 3 } : pending(l)]));
  return {
    id, title, tier: (assignee?.match(TIER_OF)?.[1] as Job["tier"] | undefined) ?? "standard", spec: "—",
    phase: cur.phase, step: Math.max(0, steps?.indexOf(state[cur.phase]) ?? 0), round: cur.round, limit: 3, attended: false,
    mins: trail.at(-1)!.mins, lenses, plan: {}, trail,
  };
}

const TIP = `position:absolute;pointer-events:none;max-width:210px;padding:6px 9px;border-radius:5px;background:${tint("bg1", 96)};border:1px solid ${tint("slate", 28)};box-shadow:0 4px 16px ${tint("shadow", 50)};font-size:.72em;line-height:1.45;color:var(--ink);z-index:5`;

const blank = (self: Scene["self"]): Scene => ({ P: { lane: [], guide: [], grp: [] }, L: [], S: [], B: [], T: [], K: [], H: [], Q: [], V: [], tips: {}, dets: {}, self, open: self.state.open, pick: self.state.pick });
const joined = (P: Scene["P"]) => ({ lane: P.lane.join(" "), guide: P.guide.join(" "), grp: P.grp.join(" ") });

/** One pass of the engine over the selected task as it was `view.at` minutes back: the fixed board, the scrolling rows, and what hover and click opened. */
export function sceneOf(jobs: Job[], view: View, setView: (patch: Partial<View>) => void, nowSec: number) {
  const d = new Date(nowSec * 1000);
  setNowMinutes(d.getHours() * 60 + d.getMinutes());
  const self = { state: view, setState: setView };
  const j0 = jobs.find((x) => x.id === view.sel) ?? jobs[0], job = jobAt(j0, view.at);
  const main = blank(self);
  template(main, STYLE, jobs, job);
  replay(main, j0, view.at, view.replaying);
  const rowScene = blank(self), rowsH = rows(rowScene, STYLE, job) + 56;

  const tipOf = (G: Scene, maxX: number) => {
    const t = view.hover ? G.tips[view.hover] : undefined;
    return t && { t: t.t, lines: t.lines.filter((s): s is string => !!s), style: `${TIP};left:${Math.min(t.x, maxX - 210)}px;top:${t.y}px` };
  };
  const det = view.det ? (main.dets[view.det] ?? rowScene.dets[view.det]) : undefined;
  const fleet = jobs.map((x) => ({
    id: x.id, on: x.id === job.id, aria: `${x.id} ${x.title}, ${statusOf(x).t}`, where:x.phase === "qa" ? "qa" : (PN[x.phase] ?? x.phase).toLowerCase(),
    pick: () => setView({ sel: x.id, open: {}, pick: {}, hover: null, det: null, at: null, replaying: false }),
    bar: `flex-basis:100%;height:2px;margin-top:5px;border-radius:1px;background:linear-gradient(90deg,${TIER[x.tier]} ${Math.round(30 + ((x.mins * 7) % 60))}%,${tint("slate", 12)} 0)`,
  }));
  return { job, main, rows: rowScene, rowsH, rowsTop: -(HAIR + 1), paths: joined(main.P), rpaths: joined(rowScene.P), tip: tipOf(main, PANE_R), rtip: tipOf(rowScene, 1186), det, fleet };
}
