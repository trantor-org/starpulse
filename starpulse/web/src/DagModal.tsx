// A DAG's modal, opened from a row of the DAGs view in the Kanban task modal's frame: the title with its state dot, the full step
// chart, this or the last run, the pool's queue slots, every Board tie with its note, and Run now in the footer.
import { useEffect } from "react";
import { chartBox, lastLine, Orb, Strip, TieChip } from "./DagParts";
import { ago, refusal, short, ties, type DagData, type Row } from "./dags";

const STATE = (r: Row) => (r.phase === "ok" ? "healthy" : r.phase === "idle" ? "never run" : r.phase === "failed" ? r.d.status : r.phase);

export function DagModal({ data, r, now, starting, refused, run, close }: {
  data: DagData; r: Row; now: number; starting: boolean; refused: string | null; run: () => void; close: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !e.defaultPrevented && close();
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [close]);
  const pool = data.pools.find((p) => p.name === r.d.pool), board = ties(data, r.d.name), why = refusal(r, starting), box = chartBox(r), live = r.d.active ?? [];
  return (
    <div id="kbm" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="modal tv dgm" role="dialog" aria-label={r.d.name}>
        <button className="x" onClick={close} aria-label="Close">✕</button>
        <div className="tvhead">
          <h2><Orb phase={r.phase} big />{short(r.d.name)}</h2>
          <div className="k">{r.d.name} · {STATE(r)} · {r.domain}{r.d.pool ? ` · pool ${short(r.d.pool)}` : ""}</div>
        </div>
        <div className="tvbody">
          {refused && <div className="editrefusal"><b>Run refused.</b> {refused}</div>}
          <section className="sec"><div className="sh"><span className="t">Steps</span><span className="n">{r.d.steps.length}</span></div>
            <div className="chart"><Strip r={r} w={box.w} h={box.h} big /></div>
          </section>
          <table><tbody>
            <tr><td>{r.phase === "running" || r.phase === "queued" ? "this run" : "last run"}</td><td>{lastLine(r, now)}</td></tr>
            <tr><td>started</td><td>{r.startedAt ? `${new Date(r.startedAt * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} (${ago(now, r.startedAt)})` : "—"}</td></tr>
            <tr><td>run</td><td className="mono">{live[0]?.runId || r.d.runId || "—"}{live.length > 1 ? ` + ${live.length - 1} more` : ""}</td></tr>
            <tr><td>queue</td><td>{pool ? <span className="slots">{Array.from({ length: Math.min(pool.cap, 12) }, (_, i) => <i key={i} className={i < pool.running ? "on" : ""} />)}{pool.cap > 12 && <em>…</em>}<span>{short(pool.name)}: {pool.running} of {pool.cap} running{pool.queued ? `, ${pool.queued} queued` : ""}</span></span> : "no pool"}</td></tr>
            <tr><td>run now</td><td>{why ? <span className="k">{why}</span> : "run-safe: StarPulse may start it"}</td></tr>
          </tbody></table>
          <section className="sec"><div className="sh"><span className="t">Board</span></div>
            {board.map((t) => (
              <div className="tierow" key={t.kind + t.text + (t.ev ?? "")}><TieChip t={t} label={t.kind === "writes" ? `writes ${t.text}` : t.kind === "acts" ? "acts" : t.text} /><span className="k">{t.note}</span></div>
            ))}
            {!board.length && <div className="k">No Board tie: this DAG neither moves a task nor is cued by one.</div>}
          </section>
        </div>
        <div className="tvfoot">
          <button className="startbtn" disabled={!!why} title={why ?? undefined} onClick={run}>▶ Run now</button>
        </div>
      </div>
    </div>
  );
}
