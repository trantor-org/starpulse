import type { Outline } from "./kanban";

/** The Kanban's milestone outline in the navigator: one row per open milestone, and a click on one sets the Kanban's milestone filter, a second click on it clears. */
export function MilestoneOutline({ rows, chosen, choose }: { rows: Outline[]; chosen: string | null; choose: (milestone: string | null) => void }) {
  return (
    <>
      <h3>Milestones{chosen !== null && <button type="button" className="clear" onClick={() => choose(null)}>clear ✕</button>}</h3>
      {rows.map((r) => (
        <button key={r.milestone} type="button" className={r.milestone === chosen ? "ms on" : "ms"} aria-pressed={r.milestone === chosen}
          onClick={() => choose(r.milestone === chosen ? null : r.milestone)}>
          <span className="id">{r.milestone}</span><span className="w">{r.done}/{r.total}</span>
          <span className="bar"><i style={{ width: `${Math.round((r.done / r.total) * 100)}%` }} /></span>
        </button>
      ))}
    </>
  );
}
