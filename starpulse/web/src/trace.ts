// The hover back-trace's model: the path a task took through a level's machine, drawn from /api/history.
import { bez, textW, type Curve, type Pt } from "./scene";
import { esc } from "./panels";
import { fmtAt, type ClockMode } from "./clock";
import type { FlowSnapshot, Machine } from "./api";

/** One lane change of a task, as `/api/history?task=` answers it: `from` is null for the task's first lane. */
export interface LaneStep {
  at: number;
  from: string | null;
  to: string;
}
/** One event of a task on a lifecycle machine, as `/api/history?task=&flow=` answers it: `state` is the state it left the task in. */
export interface MachineStep {
  at: number;
  event: string;
  state: string;
}
/** One state change of a run: the numbered hop, and how long the run stayed where it landed. */
export interface Hop {
  n: number;
  at: number;
  from: string;
  to: string;
  stay: number;
}
export interface Run {
  hops: Hop[];
  stay: Record<string, number>;
  visits: Record<string, number>;
  loops: number;
  start: number;
  end: number;
  live: boolean;
  total: number;
}

interface Step {
  at: number;
  from: string | undefined;
  to: string | undefined;
}

/**
 * One run from its steps: the hops in order (a step that stays in its state counts toward `total` but draws no hop), the time in each state
 * summed over its visits, the loops (a hop back into a state the run has been in) and the elapsed time from the first step to now, or to the
 * final state the run ended in.
 */
function runOf(steps: Step[], finals: Set<string>, now: number, total: number): Run {
  const moves = steps.filter((s): s is Step & { from: string; to: string } => !!s.from && !!s.to && s.from !== s.to);
  const stay: Record<string, number> = {}, visits: Record<string, number> = {}, seen = new Set(moves.length ? [moves[0].from] : []);
  let loops = 0, end = now, ended = false;
  const hops = moves.map((s, i): Hop => {
    if (seen.has(s.to)) loops++;
    seen.add(s.to);
    const last = i === moves.length - 1, until = moves[i + 1]?.at ?? (finals.has(s.to) ? s.at : now);
    stay[s.to] = (stay[s.to] ?? 0) + (until - s.at);
    visits[s.to] = (visits[s.to] ?? 0) + 1;
    if (last && finals.has(s.to)) [end, ended] = [s.at, true];
    return { n: i + 1, at: s.at, from: s.from, to: s.to, stay: until - s.at };
  });
  return { hops, stay, visits, loops, start: steps[0]?.at ?? now, end, live: !ended, total };
}

const finalsOf = (m: Machine) => new Set(m.states.filter((s) => s.final).map((s) => s.id));

/** A lane name from the history (`In Progress`) as the Board state it names. */
const laneId = (board: Machine, name: string) => board.states.find((s) => s.id === name || s.name.toLowerCase() === name.toLowerCase())?.id;

/** A task's run through the Board: its lane changes, the first from `new`. */
export function laneRun(path: LaneStep[], board: Machine, now: number): Run {
  const steps = path.map((r): Step => ({ at: r.at, from: r.from === null ? "new" : laneId(board, r.from), to: laneId(board, r.to) }));
  return runOf(steps, finalsOf(board), now, steps.filter((s) => s.from !== s.to).length);
}

/** A task's run through one lifecycle machine: each event leaves it in the state the history names, the first from the machine's initial state. */
export function machineRun(path: MachineStep[], machine: Machine, total: number, now: number): Run {
  const init = machine.states.find((s) => s.initial)?.id;
  const steps = path.map((r, i): Step => ({ at: r.at, from: i ? path[i - 1].state : init, to: r.state }));
  return runOf(steps, finalsOf(machine), now, total);
}

/**
 * A task's run across a state level's bodies: each entry is a body the events placed it on, the first where it began. No body is final. The
 * primary's recorded path, when given, adds each of its states as `flow#state`, woven in by time, so the run reaches back past the loaded events.
 * The Board lane change that brought it into the level, when given, is its first hop, into the body it orbits.
 */
export function hostRun(
  events: { at: number; host: string }[],
  now: number,
  primary?: { flow: string; path: MachineStep[] },
  entry?: { at: number; from: string; to: string },
): Run {
  const enter = entry ? [{ at: entry.at, host: entry.from }, { at: entry.at, host: entry.to }] : [];
  const trail = [...enter, ...(primary?.path.map((r) => ({ at: r.at, host: `${primary.flow}#${r.state}` })) ?? []), ...events]
    .sort((a, b) => a.at - b.at)
    .filter((r, i, all) => r.host !== all[i - 1]?.host);
  const steps = trail.map((r, i): Step => ({ at: r.at, from: (trail[i - 1] ?? r).host, to: r.host }));
  return runOf(steps, new Set(), now, steps.filter((s) => s.from !== s.to).length);
}

/** A stay in its two largest units. */
export function fmtDur(secs: number): string {
  const s = Math.max(0, secs), m = Math.round(s / 60), h = Math.floor(m / 60), d = Math.floor(h / 24);
  return d >= 2 ? `${d}d ${h % 24}h` : h ? `${h}h ${m % 60}m` : s >= 60 ? `${m}m` : `${Math.round(s)}s`;
}

/** A state a run visited, as the level draws it: its disc, its name's spot and the room its orbits take. */
export interface Place {
  id: string;
  name: string;
  x: number;
  y: number;
  r: number;
  R: number;
  color: string;
  lab: Pt;
}
/** The path a hop lights, with every number it was taken under and where those numbers sit. `off` is a hop the machine has no path for. */
export interface Route {
  from: Place;
  to: Place;
  curve: Curve;
  off: boolean;
  nums: number[];
  t0: number;
  t1: number;
  badge: Pt;
}
/** The time a visited state held the run, beside it. */
export interface Pill {
  place: Place;
  x: number;
  y: number;
  text: string;
}
export interface Layout {
  routes: Route[];
  pills: Pill[];
  /** The state the run began in, when it never came back to it: ringed so the path has a visible start. */
  first: Place | null;
}

interface Box {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}
const boxAt = (x: number, y: number, w: number, h: number): Box => ({ x0: x - w / 2, x1: x + w / 2, y0: y - h / 2, y1: y + h / 2 });

/** A path's numbers sit at its middle, or slide along it to the nearest spot clear of the others' numbers, the times and the state names. */
const SLIDE = [0.5, 0.4, 0.6, 0.32, 0.68, 0.25, 0.75, 0.18, 0.82];

/**
 * What a run lights on a level: one route per distinct path it took (a hop with no path of the machine's bows well off the straight line, so it
 * reads as its own stroke), the time at each visited state on the side of it away from its name, and the spot for each route's numbers. `K` is
 * the zoom the level is drawn at: type and pads are a fixed size on screen.
 */
export function layout(run: Run, places: Record<string, Place>, edgeOf: (from: string, to: string) => Curve | null, board: boolean, K: number): Layout {
  const routes = new Map<string, Route>();
  for (const h of run.hops) {
    const a = places[h.from], b = places[h.to];
    if (!a || !b) continue;
    const key = `${h.from}>${h.to}`;
    if (!routes.has(key)) {
      const e = edgeOf(h.from, h.to), off = !e;
      const curve = e ?? { p0: a, c: { x: (a.x + b.x) / 2 - (b.y - a.y) * 0.28, y: (a.y + b.y) / 2 + (b.x - a.x) * 0.28 }, p1: b };
      const L = Math.hypot(curve.p1.x - curve.p0.x, curve.p1.y - curve.p0.y) || 1, flush = board && !off;
      routes.set(key, { from: a, to: b, curve, off, nums: [], t0: flush ? 0 : Math.min(0.4, (a.r + 2) / L), t1: flush ? 1 : 1 - Math.min(0.4, (b.r + 4) / L), badge: curve.c });
    }
    routes.get(key)!.nums.push(h.n);
  }
  const taken: Box[] = Object.values(places).map((s) => boxAt(s.lab.x, s.lab.y, textW(s.name, 13) / K, 18 / K));
  const clash = (b: Box) => taken.some((o) => b.x0 < o.x1 + 4 / K && b.x1 > o.x0 - 4 / K && b.y0 < o.y1 + 4 / K && b.y1 > o.y0 - 4 / K);
  const pills: Pill[] = [];
  for (const [id, secs] of Object.entries(run.stay)) {
    const s = places[id];
    if (!s) continue;
    const n = run.visits[id], text = `${fmtDur(secs)}${n > 1 ? ` · ${n}×` : ""}`, w = textW(text, 10.5) / K + 12 / K, h = 17 / K;
    // the time sits on the side away from the state's name, or the other side if that is taken
    const sides = s.lab.y < s.y ? [1, -1] : [-1, 1], at = (d: number) => s.y + d * (s.R + 16 / K);
    const y = sides.map(at).find((v) => !clash(boxAt(s.x, v, w, h))) ?? at(sides[0]);
    taken.push(boxAt(s.x, y, w, h));
    pills.push({ place: s, x: s.x, y, text });
  }
  for (const r of routes.values()) {
    const w = Math.max(16, textW(r.nums.join(" · "), 10.5) + 10) / K, h = 16 / K;
    const spots = SLIDE.map((t) => bez(r.curve.p0, r.curve.c, r.curve.p1, t));
    r.badge = spots.find((q) => !clash(boxAt(q.x, q.y, w, h))) ?? spots[0];
    taken.push(boxAt(r.badge.x, r.badge.y, w, h));
  }
  const first = places[run.hops[0]?.from];
  return { routes: [...routes.values()], pills, first: first && !run.stay[first.id] ? first : null };
}

/** The moons a Board task has sessions in, each with its session count, and the sub-states one of those sessions holds. */
export function sessionRings<M extends { name: string }, S extends { machine: string; state: string }>(
  flows: Record<string, FlowSnapshot>, task: string, moons: M[], subs: S[],
): { moons: [M, number][]; subs: S[] } {
  const held = Object.values(flows).filter((f) => f.name !== "board").flatMap((f) => f.agents.filter((a) => a.task === task).map((a) => ({ flow: f.name, state: a.state })));
  const per = (name: string) => held.filter((h) => h.flow === name).length;
  return {
    moons: moons.flatMap((m): [M, number][] => (per(m.name) ? [[m, per(m.name)]] : [])),
    subs: subs.filter((t) => held.some((h) => h.flow === t.machine && h.state === t.state)),
  };
}

/** What the trace is about: a Board task, or a task on one lifecycle machine. */
export type Subject = { kind: "task"; id: string } | { kind: "mtask"; id: string; flow: string };
export interface Traced {
  subject: Subject;
  /** A click pinned it: the rest of the level steps back under a veil. */
  veil: boolean;
}
type Hovered = { kind: string; o: unknown } | null;
type DagOf<H> = H extends { kind: "dag"; o: infer O } ? O : never;

/** The task a hover rests on, when it rests on one. */
export function subjectOf(h: Hovered): Subject | null {
  const o = h?.o as { id: string; flow: string } | undefined;
  return h?.kind === "task" ? { kind: "task", id: o!.id } : h?.kind === "mtask" ? { kind: "mtask", id: o!.id, flow: o!.flow } : null;
}
const same = (a: Subject, b: Subject | null) => !!b && a.kind === b.kind && a.id === b.id && (a.kind === "task" || a.flow === (b as typeof a).flow);

/**
 * What a hover and a pin draw. A task is traced and never tethered to its DAGs; a DAG is tethered and never traces. Only a pinned subject veils
 * the level, so a hover alone highlights, and the veil holds from the click while the pointer still rests on the dot.
 */
export function draws<H extends Hovered>(hover: H, pin: Subject | null, spot: Subject | null = null): { trace: Traced | null; dag: DagOf<H> | null } {
  if (hover?.kind === "dag") return { trace: null, dag: hover.o as DagOf<H> };
  // a task the Recent rail spots is traced too, even where the level lights its state body because it draws no dot for it
  const subject = subjectOf(hover) ?? spot ?? pin;
  return { trace: subject && { subject, veil: same(subject, pin) }, dag: null };
}

/** What the hover card says about the run it traces. */
export interface CardHead {
  /** The line above the id: what the traced thing is. */
  kind: string;
  id: string;
  title: string;
  /** Where a live run is headed, for the forecast slot. */
  goal: string;
}
const plural = (n: number, w: string) => `<b>${n}</b> ${w}${n === 1 ? "" : "s"}`;

export function traceCard(head: CardHead, run: Run | "loading" | "unavailable", clock: ClockMode = "24"): string {
  const top = `<div class="k">${esc(head.kind)}</div><div class="n">${esc(head.id)}</div>${esc(head.title)}`;
  if (typeof run === "string") return `${top}<div class="k">${run === "loading" ? "tracing its path…" : "history unavailable"}</div>`;
  return `${top}<div class="stats"><span>${plural(run.total, "step")}</span><span>${plural(run.loops, "loop")}</span><span><b>${fmtDur(run.end - run.start)}</b> ${run.live ? "so far" : "start to end"}</span></div>
    <div class="k">since ${fmtAt(run.start, clock)} MST</div>${run.live ? `<div class="fc">forecast · <i>Proposal D, not built</i> · e.g. 71% reach ${esc(head.goal)}, ~1d 6h left</div>` : ""}`;
}

/** The pinned panel's table: every hop with when it happened and how long the run stayed where it landed. */
export const traceTable = (run: Run, name: (id: string) => string, clock: ClockMode = "24"): string =>
  `<div class="k" style="margin-top:12px">path · ${run.total} steps · ${run.loops} loops · ${fmtDur(run.end - run.start)}</div><table class="trace">${run.hops
    .map((h) => `<tr><td>${h.n}</td><td>${fmtAt(h.at, clock)}</td><td>${esc(name(h.from))} → ${esc(name(h.to))}</td><td>${fmtDur(h.stay)}</td></tr>`)
    .join("")}</table>`;
