// Assembles the drill-in board for one task at one instant of its replay: the machines' states and rounds from the task's 24h of events, where the
// task sits, and the hop it just made. Lens machine definitions are fixtures here until each lens ships its own machine; a round starts each time
// a machine leaves "idle".
import { LENS_IDS, sunsBoard, type SunsBoard, type SunsInput } from "./sunsBoard";
import { movesBetween, stateAt, type MachineEvent } from "./sunsReplay";
import type { Travel } from "../../render/sunsDraw";

const PHASES = [["build", "Build"], ["deliver", "Deliver"], ["review_fix", "Review fix"]] as const;
const LENS_STATES = ["idle", "running", "pass", "fail"];
const ENTRIES = ["Ready"], EXITS = ["Needs Attention", "Done"];

const phaseOf = (machine: string) => (LENS_IDS.includes(machine) ? "qa" : machine);

export function drillBoard(task: SunsInput["task"], events: MachineEvent[], t: number, prevT: number): { board: SunsBoard; travel?: Travel } {
  const seen = events.filter((e) => e.at <= t), now = stateAt(seen, t);
  const machine = (id: string, name: string) => {
    const rounds = Math.max(1, seen.filter((e) => e.machine === id && e.from === "idle").length);
    return { id, name, state: now[id]?.state ?? "idle", rounds, round: rounds };
  };
  const last = seen.at(-1), phase = last ? phaseOf(last.machine) : "build";
  const input: SunsInput = {
    task, phase,
    phases: PHASES.map(([id, name]) => machine(id, name)),
    lenses: LENS_IDS.map((id) => ({ ...machine(id, id), states: LENS_STATES })),
    entries: ENTRIES, exits: EXITS,
  };
  const board = sunsBoard(input);

  // Only a forward step that changes the phase animates; scrubbing back, or a move inside a phase, leaves the task still.
  const before = events.filter((e) => e.at <= prevT).at(-1), from = before ? phaseOf(before.machine) : "build";
  const hop = movesBetween(events, prevT, t).findLast((e) => phaseOf(e.machine) !== from);
  if (!hop || phase === from) return { board };
  const pos = (p: string) => (p === "qa" ? board.dots[0] : board.suns.find((s) => s.id === p)!);
  return { board, travel: { from: { x: pos(from).x, y: pos(from).y }, to: board.task.at, at: hop.at } };
}
