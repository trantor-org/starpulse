import type { KanbanTask } from "./kanban";
import { age, leaderboard } from "./leaderboard";

/**
 * The Star Map navigator's Leaderboard: for each open status, the workable tasks that have been workable longest, each a row
 * with its age and a bar against the longest shown. A click or Enter on a row opens the task as a search hit does.
 * Nothing is drawn while no task is workable.
 */
export function Leaderboard({ tasks, now, open }: { tasks: KanbanTask[]; now: number; open: (id: string) => void }) {
  const groups = leaderboard(tasks, now);
  if (!groups.length) return null;
  return (
    <section className="away leaderboard">
      <h3>Leaderboard<span className="sub">by status</span></h3>
      {groups.map((g) => (
        <div key={g.status}>
          <div className="lb-grp" title={g.held ? `${g.held} more can't be worked yet` : undefined}><span>{g.label}</span><span className="n">{g.workable}</span></div>
          {g.rows.map((r) => (
            <button key={r.id} type="button" className="lb-row" title={`${r.title}\n${g.label.toLowerCase()} for ${age(r.seconds)}`}
              onClick={() => open(r.id)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), open(r.id))}>
              <span className="id">{r.id}</span><span className="w">{age(r.seconds)}</span>
              <span className="bar"><i style={{ width: `${r.width}%` }} /></span>
            </button>
          ))}
        </div>
      ))}
    </section>
  );
}
