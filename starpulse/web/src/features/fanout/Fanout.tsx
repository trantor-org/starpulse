// The two places the navigator and the right rail show a DAG's fan-out: every concurrency pool's load, and the Recent feed's lines.
import { poolRows } from "./fanout";
import type { FeedLine } from "../../render/hud";
import type { Pool } from "../../api";

/** The navigator's Queues section: each pool's running runs against its cap with any waiting, and a meter that turns red when it is full. Nothing when the adapter reports no pools. */
export function Queues({ pools }: { pools: Pool[] | undefined }) {
  const rows = poolRows(pools);
  if (!rows.length) return null;
  return (
    <section className="away">
      <h3>Queues</h3>
      <div id="queues">
        {rows.map((p) => (
          <div key={p.name} className={["q", p.full ? "full" : p.busy && "busy"].filter(Boolean).join(" ")} title={p.name}>
            <div className="r">
              <span>{p.label}</span>
              <b>{p.count}{p.queued && ` ${p.queued}`}</b>
            </div>
            <div className="m"><i style={{ width: `${p.pct}%` }} /></div>
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * The Recent feed: a move or a run's line each, a run's outcome coloured, and a line born after the page's first read flashing once as it mounts.
 * A line the view `can` light reports its hover to `spot` and its click to `pick`; `note` says on the hovered line why the view does not show it.
 */
export function FeedLines({ lines, can, spot, pick, note }: {
  lines: FeedLine[]; can?: (l: FeedLine) => boolean; spot?: (l: FeedLine | null) => void; pick?: (l: FeedLine) => void;
  note?: { key: string; text: string } | null;
}) {
  return (
    <>
      {lines.map((f) => {
        const go = !!(can?.(f) && spot && pick), cls = [f.fresh && "new", go && "go"].filter(Boolean).join(" ");
        return (
          <div key={f.key + f.at} className={cls || undefined}
            onPointerEnter={go ? () => spot!(f) : undefined} onPointerLeave={go ? () => spot!(null) : undefined} onClick={go ? () => pick!(f) : undefined}>
            <em>{f.time}</em> <b>{f.who}</b>{f.what && ` ${f.what}`} <em className={f.tone}>{f.where}</em>
            {go && note?.key === f.key && <span className="why">{note.text}</span>}
          </div>
        );
      })}
    </>
  );
}
