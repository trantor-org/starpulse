// The tooltips of the DAGs tied to a Board state (D7b). Status lives here and in the drill-in, never as text on the map.
import type { Dag } from "../api";
import type { Hub, Orbiter } from "./dagTies";
import { esc } from "./panels";
import type { Sky } from "./sky";

export type TipSky = Pick<Sky, "dagBy" | "cues" | "board">;
interface Ctx {
  sky: TipSky;
  stateName: (id: string) => string;
}

/** A tied DAG's status as the tooltip names it: its last run's, a failed one standing until the next green run clears it. */
export const tieStatus = (d: Dag | undefined) => (d?.status === "failed" ? "failed · unresolved" : (d?.status ?? ""));

/** A hangar's tooltip: the DAGs it holds with their status, and what a click and a right-click do. */
export function hubTip(h: Pick<Hub, "state" | "orbs">, { sky, stateName }: Ctx): string {
  const rows = h.orbs.map((o) => `${esc(o.label)} <span class="k">${o.primary?.kind === "cue" ? "cued by" : "writes"} ${esc(o.primary?.event ?? "")} · ${esc(tieStatus(sky.dagBy[o.dag]))}</span>`);
  return `<div class="k">DAGs that act on ${esc(stateName(h.state))} · click opens their Ledger · right-click comes back</div><div class="n">DAGs · ${esc(stateName(h.state))}</div>${rows.join("<br>")}`;
}

/** An orbiter's tooltip: its DAG's status, the Ledger a click opens (`ev`, null for none) and each tie. `last` words the DAG's last run. */
export function tieTip(o: Orbiter, { sky, stateName, ev, last }: Ctx & { ev: string | null; last: (d: Dag) => string }): string {
  const d = sky.dagBy[o.dag], cue = (e: string) => sky.cues.find((c) => c.dag === o.dag && c.event === e);
  const rows = o.anchors.map((a) => {
    if (a.kind === "write") {
      const tr = sky.board.machine.transitions.find((x) => x.event === a.event);
      return `writes ${esc(a.event)} <span class="k">${tr ? `${esc(stateName(tr.source))} → ${esc(stateName(tr.target))}` : ""}</span>`;
    }
    const r = cue(a.event)?.resolves;
    return `cued by ${esc(a.event)} <span class="k">${r ? `· a failed run clears ${r === "forced" ? "only on a green forced rerun" : "on its next green run"}` : ""}</span>`;
  });
  for (const s of o.subs) rows.push(`writes the states of ${esc(s.flow)}`);
  return `<div class="k">DAG tied to the Board · ${esc(tieStatus(d))} · ${ev ? `click for the ${esc(ev)} Ledger` : "no Ledger to open"}</div><div class="n">${esc(o.dag)}</div>${rows.join("<br>")}${d?.finishedAt ? `<div class="k">${esc(last(d))}</div>` : ""}`;
}
