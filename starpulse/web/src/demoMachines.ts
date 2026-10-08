// A demo page's machines grown to a count (`?demo&many=N`), so the In Progress ledger has more than a page to scroll and a 24 h strip to draw.
import { PAGE } from "./machineLanes";
import type { FlowSnapshot, MachineEntry, Snapshot } from "./api";

const DAY = 86400;
/** The seconds from now to a machine's last move, spread over the day: close together near now, wide apart far back. */
const FROM = ["ready", "in_progress", "review", "waiting"];
const age = (i: number, n: number) => 90 + Math.round((DAY - 600) * (i / Math.max(1, n - 1)) ** 1.6);

/** `snap` with the machines under its open one cloned from the ones it has until there are `n`, their last moves spread over the 24 hours, the first page and the strip drawn over them. */
export function padMachines(snap: Snapshot, n: number): Snapshot {
  const top = snap.machinePage?.open;
  const kids = snap.flows.filter((f) => f.parent === top && f.name !== top);
  if (!top || !kids.length || kids.length >= n) return snap;
  const made: FlowSnapshot[] = Array.from({ length: n }, (_, i) => {
    const from = kids[i % kids.length], last = snap.now - age(i, n);
    return {
      ...from,
      name: `${from.name}-${String(i + 1).padStart(2, "0")}`,
      last,
      agents: from.agents.map((a) => {
        const id = `${a.id}-${i + 1}`, trail = (a.trail ?? []).map((s, k, all) => ({ ...s, at: last - 400 * (all.length - 1 - k) }));
        return { ...a, id, task: id, trail, active: last };
      }),
    };
  });
  const newest = [...made].sort((a, b) => b.last! - a.last! || (a.name < b.name ? -1 : 1)).map((f) => f.name);
  const entries: MachineEntry[] = made.flatMap((f, i) =>
    f.agents.flatMap((a, k) =>
      (a.trail ?? []).map((s, j): MachineEntry => ({
        at: s.at,
        machine: f.name,
        row: f.name,
        from: j === 0 ? { machine: "board", state: FROM[(i + k) % FROM.length] } : null,
        dag: j === 0 && k === 0 && i % 7 === 3 ? "nightly-sweep" : null,
      })),
    ),
  ).filter((e) => e.at > snap.now - DAY).sort((a, b) => a.at - b.at);
  return {
    ...snap,
    flows: [...snap.flows.filter((f) => f.parent !== top || f.name === top).map((f) => (f.name === top ? { ...f, nested: newest } : f)), ...made],
    machinePage: { open: top, machines: newest.slice(0, PAGE), more: n > PAGE },
    machineStrip: { entries },
  };
}
