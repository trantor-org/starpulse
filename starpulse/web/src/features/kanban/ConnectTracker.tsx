// The Kanban toolbar's Connect a tracker: a modal with one collapsible row per tracker, each expanding to numbered setup steps whose commands copy.
import { useEffect, useRef, useState } from "react";
import { copyToClipboard } from "./taskView";

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
  {
    name: "Backlog.md",
    about: "Draws a Backlog.md project's tasks and writes each move with its backlog CLI.",
    steps: [
      { text: "Install the Backlog.md CLI, which writes each move:", cmd: "npm i -g backlog.md" },
      { text: "Connect the project's backlog/ directory:", cmd: "starpulse connect backlog --path backlog", out: "✓ Read 36 tasks in 5 lanes from backlog/ · wrote [board] to starpulse.toml" },
      { text: "Restart the server to draw it:", cmd: "starpulse serve" },
    ],
  },
  {
    name: "Jira", badge: "read-only",
    about: "Imports a Jira project's workflow as the Board machine and reads its issues. Moves are made in Jira.",
    steps: [
      { text: "Create an API token in your Atlassian account settings, then export it:", cmd: "export JIRA_TOKEN=<your API token>" },
      {
        text: "Connect the project. It checks the site and the token, imports the workflow and reads the issues once:",
        cmd: 'starpulse connect jira --url https://<your-site>.atlassian.net --project PAY --workflow "Payments Software Workflow" --user <your Atlassian email>',
        out: "✓ Imported Payments Software Workflow (7 states) · read 42 issues from PAY · wrote [board] to starpulse.toml",
      },
      { text: "Restart the server to draw it:", cmd: "starpulse serve" },
    ],
  },
];

const RUN = " run: ";

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

/** The server's hint ends `… run: <command>`: the prose, then the command to draw as a block. */
function Found({ hint }: { hint: string }) {
  const at = hint.lastIndexOf(RUN);
  return (
    <div className="found" role="status">
      {at < 0 ? hint : hint.slice(0, at + RUN.length - 1)}
      {at >= 0 && <CmdBlock cmd={hint.slice(at + RUN.length)} />}
    </div>
  );
}

export function TrackerModal({ hint, close }: { hint?: string | null; close: () => void }) {
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
        {hint && <Found hint={hint} />}
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

export function ConnectTracker({ hint }: { hint?: string | null }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="trackerw">
      <button className="tbtn" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>Connect a tracker</button>
      {open && <TrackerModal hint={hint} close={() => setOpen(false)} />}
    </span>
  );
}
