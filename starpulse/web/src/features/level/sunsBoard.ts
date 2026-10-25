// The In Progress drill-in, "B · Suns": one folded row per machine (Build, the four QA lenses, Deliver, Review fix), each a sun, its current
// state and r1..rN round pills, every stem running along the row's hairline into one routing track. Entry flows come in from the left edge and
// exits leave the right edge, each named above a flat run. Groups are separated by lines (Build | lenses | Deliver | Review fix) and rows never
// are. Pure layout; the renderer (render/sunsDraw.ts) draws it and moves the task with orbitTasks.
import { tierColor } from "../../render/draw";

export const LENS_IDS = ["security", "ux", "ui", "code"];

export interface SunsMachineIn {
  id: string;
  name: string;
  /** The state it is in now. */
  state: string;
  rounds: number;
  /** The round shown, 1-based. */
  round: number;
}
export interface SunsLensIn extends SunsMachineIn {
  states: string[];
}
export interface SunsInput {
  task: { id: string; profile?: string };
  /** Where the task is: build, qa (all four lenses), deliver or review_fix. */
  phase: string;
  phases: SunsMachineIn[];
  lenses: SunsLensIn[];
  /** Flows that enter the board from other states, and the exits that leave Deliver, each listed top to bottom as drawn. */
  entries: string[];
  exits: string[];
}

export interface Label {
  text: string;
  x: number;
  /** Baseline. */
  y: number;
  w: number;
  h: number;
}
export interface Sun {
  id: string;
  x: number;
  y: number;
  r: number;
  color: string;
  label: Label;
}
export interface Pill {
  label: string;
  x: number;
  y: number;
  current: boolean;
}
export interface Row {
  id: string;
  name: string;
  y: number;
  /** Only the current state is named. */
  state: string;
  stateX: number;
  pills: Pill[];
}
export interface Stem {
  row: string;
  points: { x: number; y: number }[];
  /** The radius every stem turns into the track with: the same for phases and lenses. */
  arc: number;
}
export interface Flow {
  /** The flat run the label sits above. */
  line: { x0: number; x1: number; y: number };
  /** Where the run meets the board (curved by the renderer). */
  join: { x: number; y: number };
  label: Label;
  /** Arrowhead length for an exit, 0 for an entry. */
  arrow: number;
}
export interface SunsBoard {
  width: number;
  height: number;
  suns: Sun[];
  dots: { id: string; x: number; y: number }[];
  rows: Row[];
  groups: { id: string; rows: string[] }[];
  separators: { y: number; x0: number; x1: number }[];
  track: { x: number; y0: number; y1: number };
  stems: Stem[];
  entries: Flow[];
  exits: Flow[];
  task: { id: string; color: string; ring: string; at: { x: number; y: number } };
}

const W = 880, TOP = 96, PITCH = 52, GAP = 22, SUN_X = 120, SUN_R = 11, STATE_X = 150, PILL_X = 330, PILL_STEP = 34, TRACK_X = 540, ARC = 14;
const FLOW_PITCH = 44, LABEL_H = 12, LABEL_RISE = 7, ARROW = 8, ARROW_GAP = 8, CHAR_W = 6.2, PHASE = "#3b82f6", LENS = "#14b8a6", PERSON = "#e2e8f0";
// The tier swatch for an agent. A person or fast task has no tier, and tierColor's fallback for it is yellow, which the board never draws.
const taskColor = (profile?: string) => {
  const c = tierColor(profile);
  return c === "#fde68a" ? PERSON : c;
};
const textW = (s: string) => Math.round(s.length * CHAR_W);

export function sunsBoard(d: SunsInput): SunsBoard {
  const byId = new Map<string, SunsMachineIn & { states?: string[] }>([...d.phases, ...d.lenses].map((m) => [m.id, m]));
  const groups = [{ id: "build", rows: ["build"] }, { id: "lenses", rows: LENS_IDS }, { id: "deliver", rows: ["deliver"] }, { id: "review_fix", rows: ["review_fix"] }];
  const rows: Row[] = [], suns: Sun[] = [], separators: SunsBoard["separators"] = [];
  let y = TOP;
  for (const [gi, g] of groups.entries()) {
    if (gi) y += GAP;
    for (const id of g.rows) {
      const m = byId.get(id)!;
      rows.push({ id, name: m.name, y, state: m.state, stateX: STATE_X,
        pills: Array.from({ length: m.rounds }, (_, i) => ({ label: `r${i + 1}`, x: PILL_X + i * PILL_STEP, y, current: i + 1 === m.round })) });
      suns.push({ id, x: SUN_X, y, r: SUN_R, color: LENS_IDS.includes(id) ? LENS : PHASE,
        label: { text: m.name, x: SUN_X, y: y - SUN_R - 6, w: textW(m.name), h: LABEL_H } });
      y += PITCH;
    }
  }
  // A separator sits midway between the last row of a group and the first of the next.
  for (const [i, g] of groups.slice(1).entries()) {
    const above = rows.find((r) => r.id === groups[i].rows.at(-1))!, below = rows.find((r) => r.id === g.rows[0])!;
    separators.push({ y: (above.y + below.y) / 2, x0: 0, x1: W });
  }

  const row = (id: string) => rows.find((r) => r.id === id)!;
  const lensRows = LENS_IDS.map(row);
  const mid = (lensRows[0].y + lensRows.at(-1)!.y) / 2;
  const dots = [{ id: "fork", x: SUN_X - 36, y: mid }, { id: "join", x: TRACK_X + 28, y: mid }];
  const track = { x: TRACK_X, y0: rows[0].y, y1: rows.at(-1)!.y };
  const stems = rows.map((r) => ({ row: r.id, points: [{ x: SUN_X + SUN_R, y: r.y }, { x: TRACK_X, y: r.y }], arc: ARC }));

  const build = row("build"), deliver = row("deliver");
  const entries = d.entries.map((text, i): Flow => {
    const fy = build.y + (i - (d.entries.length - 1) / 2) * FLOW_PITCH;
    return { line: { x0: 0, x1: SUN_X - 56, y: fy }, join: { x: SUN_X - SUN_R, y: build.y }, arrow: 0,
      label: { text, x: 8, y: fy - LABEL_RISE, w: textW(text), h: LABEL_H } };
  });
  // Exits fan out in the order given, so two curves from one join never cross.
  const exits = d.exits.map((text, i): Flow => {
    const fy = deliver.y + (i - (d.exits.length - 1) / 2) * FLOW_PITCH;
    const x1 = W, w = textW(text);
    return { line: { x0: TRACK_X + 70, x1, y: fy }, join: { x: TRACK_X, y: deliver.y }, arrow: ARROW,
      label: { text, x: x1 - ARROW - ARROW_GAP - w, y: fy - LABEL_RISE, w, h: LABEL_H } };
  });
  const color = taskColor(d.task.profile);
  const at = d.phase === "qa" ? dots[0] : suns.find((s) => s.id === d.phase)!;
  return { width: W, height: y, suns, dots, rows, groups, separators, track, stems, entries, exits,
    task: { id: d.task.id, color, ring: color, at: { x: at.x, y: at.y } } };
}
