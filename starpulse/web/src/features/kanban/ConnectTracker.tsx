// The Kanban toolbar's Connect a tracker: a modal with one collapsible row per tracker, each expanding to numbered setup steps whose commands copy.
import { useEffect, useRef, useState } from "react";
import { copyToClipboard } from "./taskViewModel";

interface Step { text: string; cmd?: string; out?: string }
interface Tracker { name: string; badge?: string; about: string; steps: Step[] }

/** The trackers a board can be drawn from. GitHub is a pull-request adapter, not a board, so it is not here. */
export const TRACKERS: Tracker[] = [
  {
    name: "StarPulse board", badge: "connected",
    about: "StarPulse's own Markdown board, drawn until you connect another. Moves made on the page are written to it.",
    steps: [
      { text: "Nothing to set up: the board is created empty in .starpulse/board on the first serve." },
      { text: "To keep it somewhere else, or give it a machine file that decides which moves are offered:", cmd: "starpulse connect native --path .starpulse/board --machine board.yaml" },
    ],
  },
];

/** A command in a block: `$`, the command wrapped, and a Copy button that puts exactly the command on the clipboard. */
function CmdBlock({ cmd }: { cmd: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(t);
  }, [copied]);
  return (
    <div className="cmd">
      <span className="ps">$</span>
      <code>{cmd}</code>
      <button className={`tm-copy${copied ? " ok" : ""}`} aria-label={`Copy ${cmd}`} onClick={() => void copyToClipboard(cmd).then((ok) => ok && setCopied(true))}>
        <span className="g">⧉</span>{copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export function TrackerModal({ close }: { close: () => void }) {
  const [on, setOn] = useState<ReadonlySet<string>>(new Set());
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    dialog.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !e.defaultPrevented && close();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [close]);
  const toggle = (name: string) => setOn((s) => { const n = new Set(s); if (!n.delete(name)) n.add(name); return n; });
  return (
    <div id="tkm" onClick={(e) => e.target === e.currentTarget && close()}>
      <div className="modal tk" role="dialog" aria-label="Connect a tracker" tabIndex={-1} ref={dialog}>
        <div className="tkhead"><h2>Connect a tracker</h2><button className="x" aria-label="Close" onClick={close}>✕</button></div>
        <p className="k">StarPulse draws its own Markdown board until you connect another. <code>starpulse connect</code> checks that the tracker answers, then writes the board settings into <code>starpulse.toml</code> for you; <code>starpulse connect --help</code> lists every option.</p>
        <div className="tklist">
          {TRACKERS.map((t) => (
            <section key={t.name} className={`tk${on.has(t.name) ? " on" : ""}`}>
              <button className="tk-row" aria-expanded={on.has(t.name)} onClick={() => toggle(t.name)}>
                <span className="chev">{on.has(t.name) ? "▾" : "▸"}</span><b>{t.name}</b>
                {t.badge && <span className={`badge ${t.badge}`}>{t.badge}</span>}
                <span className="about">{t.about}</span>
              </button>
              {on.has(t.name) && (
                <ol className="tk-body">
                  {t.steps.map((s) => (
                    <li key={s.text}>
                      <div>{s.text}</div>
                      {s.cmd && <CmdBlock cmd={s.cmd} />}
                      {s.out && <div className="out"><span className="k">prints </span>{s.out}</div>}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The Admin view's Tracker card: which tracker the board is drawn from, and the setup steps for connecting another. */
export function TrackerCard() {
  const [open, setOpen] = useState(false);
  return (
    <section className="card">
      <h2>Tracker <span className="c">where the board's tasks come from</span></h2>
      <div className="row">
        <div><div className="lb">Board source</div><div className="hint">StarPulse's own Markdown board until you connect another</div></div>
        <div><button type="button" className="btn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>Connect a tracker</button></div>
      </div>
      {open && <TrackerModal close={() => setOpen(false)} />}
    </section>
  );
}
