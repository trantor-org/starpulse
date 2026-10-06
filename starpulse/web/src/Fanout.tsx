// The two places the navigator and the right rail show a DAG's fan-out: every concurrency pool's load, and the Recent feed's lines.
import { poolRows } from "./fanout";
import type { FeedLine } from "./hud";
import type { Pool } from "./types";

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

/** The Recent feed: a move or a run's line each, a run's outcome coloured, and a line born after the page's first read flashing once as it mounts. */
export function FeedLines({ lines }: { lines: FeedLine[] }) {
  return (
    <>
      {lines.map((f) => (
        <div key={f.key + f.at} className={f.fresh ? "new" : undefined}>
          <em>{f.time}</em> <b>{f.who}</b>{f.what && ` ${f.what}`} <em className={f.tone}>{f.where}</em>
        </div>
      ))}
    </>
  );
}
