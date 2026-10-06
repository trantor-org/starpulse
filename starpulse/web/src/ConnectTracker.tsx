// The Kanban toolbar's Connect a tracker: a panel with the [board] configuration of each public adapter, and the Backlog.md project serve found.
import { useState } from "react";

/** The public board adapters and the `[board]` table that shows each one. */
export const TRACKERS = [
  {
    name: "Backlog.md",
    about: "Draws a Backlog.md project's tasks and writes a move with its backlog CLI.",
    config: '[board]\ntype = "upstream_backlog"\npath = "backlog"     # the project\'s backlog/ directory, relative to this file\ncommand = "backlog"  # the Backlog.md CLI that writes a move',
  },
];

export function TrackerPanel({ hint, close }: { hint?: string | null; close: () => void }) {
  return (
    <div className="trackers" role="dialog" aria-label="Connect a tracker">
      <div className="hd"><b>Connect a tracker</b><button className="tbtn" aria-label="Close" onClick={close}>×</button></div>
      <p>StarPulse shows its own Markdown board until <code>starpulse.toml</code> names another. Add the table for your tracker, then restart <code>starpulse serve</code>.</p>
      {hint && <div className="found" role="status">{hint}</div>}
      {TRACKERS.map((t) => (
        <section key={t.name}>
          <h4>{t.name}</h4>
          <div className="k">{t.about}</div>
          <pre>{t.config}</pre>
        </section>
      ))}
    </div>
  );
}

export function ConnectTracker({ hint }: { hint?: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="trackerw">
      <button className="tbtn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>Connect a tracker</button>
      {open && <TrackerPanel hint={hint} close={() => setOpen(false)} />}
    </span>
  );
}
