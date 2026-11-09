// A demo page's machines grown to a count (`?demo&many=N`), so the In Progress ledger has more than a page to scroll and a 24 h strip to draw.
import { PAGE } from "../features/level/machineLanes";
import type { FlowSnapshot, MachineEntry, Roles, Snapshot } from "../api";

const DAY = 86400;
/** The seconds from now to a machine's last move, spread over the day: close together near now, wide apart far back. */
const FROM = (roles: Roles) => [roles.ready ?? "", roles.working ?? "", roles.review ?? "", roles.waiting ?? ""];
const age = (i: number, n: number) => 90 + Math.round((DAY - 600) * (i / Math.max(1, n - 1)) ** 1.6);

/** `snap` with the machines under its open one cloned from the ones it has until there are `n`, their last moves spread over the 24 hours, the first page and the strip drawn over them. */
export function padMachines(snap: Snapshot, n: number): Snapshot {
  const top = snap.machinePage?.open;
  const from_ = FROM(snap.roles ?? {});
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
        from: j === 0 ? { machine: "board", state: from_[(i + k) % from_.length] } : null,
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

/** The fourteen-state Board's tiers: the states that play a role are the Board's own, the rest are named here. */
const tiers14 = (r: Roles) => [["new"], ["triage"], [r.ready ?? "", r.waiting ?? "", "blocked"], [r.attention ?? ""], [r.working ?? ""], ["qa"], ["staging"], [r.review ?? ""], ["approved"], [r.done ?? "", "closed", "completed"]];
const paths14 = (r: Roles) => {
  const [ready, waiting, working, review, attention, done] = [r.ready, r.waiting, r.working, r.review, r.attention, r.done];
  return `new>triage triage>${ready} ${ready}>${working} ${working}>qa qa>staging staging>${review} ${review}>approved approved>${done} ${done}>completed
  ${ready}>${waiting} ${waiting}>${ready} ${ready}>blocked blocked>${ready} ${working}>${waiting} ${waiting}>${working} ${working}>${attention} ${attention}>${ready}
  ${attention}>${working} qa>${working} ${review}>${working} staging>qa ${review}>${done} ${review}>closed ${done}>closed ${ready}>closed new>${ready}
  new>${working} triage>blocked blocked>${attention} approved>closed qa>${attention} ${waiting}>closed completed>closed`.split(/\s+/).map((p) => p.split(">"));
};

/** `snap` with its Board reshaped for a Star Map review (`?demo&board=`): `no-archived` and `no-attention` take that state out, `unlisted` adds one no tier names joined to Ready and In Progress, `fourteen` draws fourteen states over thirty-three paths. Any other value leaves it alone. */
export function shapeBoard(snap: Snapshot, variant: string | null): Snapshot {
  const at = snap.flows.findIndex((f) => f.name === "board");
  if (at < 0) return snap;
  const roles = snap.roles ?? {}, tiers = tiers14(roles), { machine, agents } = snap.flows[at], out = (...gone: string[]) => ({
    machine: {
      ...machine,
      states: machine.states.filter((s) => !gone.includes(s.id)),
      transitions: machine.transitions.filter((t) => !gone.includes(t.source) && !gone.includes(t.target)),
      mainLine: machine.mainLine?.filter((id) => !gone.includes(id)),
    },
    agents: agents.filter((a) => !gone.includes(a.state)),
  });
  const shaped: Partial<Pick<FlowSnapshot, "machine" | "agents">> | null =
    variant === "no-archived" ? out(...machine.states.filter((s) => s.final).map((s) => s.id))
    : variant === "no-attention" ? out(roles.attention ?? "")
    : variant === "unlisted" ? {
      machine: {
        ...machine,
        states: [...machine.states, { id: "held", name: "Held", initial: false, final: false }],
        transitions: [...machine.transitions, { source: roles.ready ?? "", target: "held", event: "ready_held" }, { source: "held", target: roles.working ?? "", event: "held_working" }],
      },
    }
    : variant === "fourteen" ? {
      machine: {
        ...machine,
        states: tiers.flat().map((id, i) => ({ id, name: id, initial: i === 0, final: ["closed", "completed"].includes(id) })),
        transitions: paths14(roles).map(([source, target]) => ({ source, target, event: `${source}_${target}` })),
        mainLine: ["new", "triage", roles.ready ?? "", roles.working ?? "", "qa", "staging", roles.review ?? "", "approved", roles.done ?? ""],
        tiers,
      },
    }
    : null;
  return shaped ? { ...snap, flows: snap.flows.map((f, i) => (i === at ? { ...f, ...shaped } : f)) } : snap;
}
