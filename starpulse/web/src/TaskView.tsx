// The task view: one task as the approved layout draws it in read mode. A fixed header, a scrolling body of fields and a fixed
// footer. Every editable field is framed and locked, so the edit slice only unlocks controls that are already drawn.
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { COLUMNS, type KanbanTask } from "./kanban";
import { startLane, startable } from "./start";
import { PRIORITIES, menuKey, type Item, type MenuState, type TaskRecord } from "./taskView";

export interface TaskViewProps {
  task: KanbanTask;
  /** The full record from /api/task/<id>; null until it arrives or when the board cannot read it. */
  record: TaskRecord | null;
  lane: string;
  /** The machine row's text: what last placed the task and when. */
  machine: string;
  /** The profiles and milestones other tasks hold, which a select offers beside the task's own. */
  profiles: string[];
  milestones: string[];
  /** The writer's or the guard's refusal and a failed session start, drawn by the caller. */
  refusal: ReactNode;
  startNote: ReactNode;
  /** What the board writes; Edit and Archive… are drawn only for what it can. */
  capabilities?: { edit: boolean; archive: boolean };
  names?: Record<string, string>;
  saving: boolean;
  claiming: boolean;
  close: () => void;
  hide: () => void;
  constellation: () => void;
  move: (to: string) => void;
  start: () => void;
  edit?: () => void;
  archive?: () => void;
}

/** A textarea that is always framed and, unless `long`, as tall as its text; `long` keeps a fixed box that scrolls inside. */
function Txt({ value, label, className = "", long }: { value: string; label: string; className?: string; long?: boolean }) {
  const el = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const t = el.current;
    if (!t || long) return;
    t.style.height = "auto";
    t.style.height = `${t.scrollHeight + 2}px`;
  }, [value, long]);
  return <textarea ref={el} className={`fv${long ? " long" : ""}${className && ` ${className}`}`} rows={long ? 7 : 1} value={value} placeholder="—" aria-label={label} readOnly tabIndex={long ? 0 : -1} />;
}

/** A select showing `value` among `options`; read mode locks it. */
function Select({ value, options, label }: { value: string; options: [string, string][]; label: string }) {
  const known = options.some(([v]) => v === value) ? options : [...options, [value, value] as [string, string]];
  return (
    <select className="fv" aria-label={label} value={value} disabled>
      {known.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
  );
}

function Chips({ values, flag }: { values: string[]; flag?: string }) {
  return (
    <div className="fv chips">
      {values.length ? values.map((v) => <span key={v} className={`chip${v === flag ? " nh" : ""}`}>{v}</span>) : <span className="none">—</span>}
    </div>
  );
}

function Checks({ name, items }: { name: string; items: Item[] }) {
  return (
    <section className="sec">
      <div className="sh"><span className="t">{name}</span><span className="n">{items.filter((i) => i.checked).length}/{items.length}</span></div>
      <div className="list">
        {items.map((i) => (
          <div key={i.n} className={`item${i.checked ? " done" : ""}`}>
            <input type="checkbox" checked={i.checked} disabled aria-label={`${name} #${i.n} done`} />
            <input type="text" className="fv" value={i.text} readOnly tabIndex={-1} aria-label={`${name} #${i.n}`} />
          </div>
        ))}
      </div>
    </section>
  );
}

const SHUT: MenuState = { open: false, on: -1 };

/** Move to: one menu of the lanes the Board machine offers, opening upward over the body, driven by the keyboard as menuKey says. */
function MoveMenu({ items, saving, move }: { items: { to: string; text: string; allowed: boolean; reason: string }[]; saving: boolean; move: (to: string) => void }) {
  const [menu, setMenu] = useState<MenuState>(SHUT);
  const enabled = items.map(() => !saving);
  const pick = (i: number) => { setMenu(SHUT); move(items[i].to); };
  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = menuKey(menu, e.key, enabled);
    if (!step.handled && step.state === menu) return;
    if (step.handled) { e.preventDefault(); e.stopPropagation(); }
    setMenu(step.state);
    if (step.pick !== null) pick(step.pick);
  };
  return (
    <div className="mv" onKeyDown={onKeyDown}>
      <div className="mvmenu" role="menu" hidden={!menu.open}>
        {items.map((it, i) => (
          <div key={it.to} role="menuitem" className={`${it.allowed ? "ok" : "guard"}${i === menu.on ? " on" : ""}`} aria-disabled={saving} title={it.allowed ? undefined : it.reason}
            onMouseMove={() => setMenu({ open: true, on: i })} onClick={(e) => { e.stopPropagation(); if (!saving) pick(i); }}>
            <span className="g">{it.allowed ? "→" : "⊘"}</span>{it.text}
          </div>
        ))}
      </div>
      <button className="mvbtn" aria-haspopup="menu" aria-expanded={menu.open} disabled={!items.length}
        title={items.length ? undefined : "no moves from here"}
        onClick={() => setMenu(menu.open ? SHUT : { open: true, on: 0 })}>Move to</button>
    </div>
  );
}

export function TaskView(p: TaskViewProps) {
  const { task, record: r } = p;
  const names = p.names ?? {};
  const own = (f: string | undefined, snapshot: string) => (r ? (f ?? "") : snapshot);
  const profile = own(r?.profile, task.assignee);
  const milestone = own(r?.milestone, task.milestone);
  const labels = r?.labels ?? task.labels;
  const deps = r?.dependencies ?? task.dependencies;
  // the board stores a priority in lower case; the select's options are capitalised
  const priority = PRIORITIES.find((v) => v.toLowerCase() === r?.priority.toLowerCase()) ?? r?.priority ?? "";
  const offered = COLUMNS.filter((c) => c in task.moves).map((c) => ({ to: c, text: names[c] ?? c, allowed: task.moves[c].allowed, reason: task.moves[c].reason }));
  const startVisible = startLane(task) && !p.claiming;
  return (
    <div className="modal tv" role="dialog" aria-label={task.id}>
      <button className="x" onClick={p.close} aria-label="Close">✕</button>
      <div className="tvhead">
        <div className="ttl">
          <Txt value={r?.title ?? task.title} label="Title" className="title" />
          <div className="k">{task.id} · {p.lane}{p.saving ? " · saving" : ""} · <a href="/" onClick={(e) => { e.preventDefault(); p.constellation(); }}>Open in Star Map ↗</a></div>
        </div>
        <div className="acts">
          <button className="hidebtn" onClick={p.hide}>Hide task</button>
          {p.capabilities?.archive && <button className="archbtn" onClick={p.archive}>Archive…</button>}
          {p.capabilities?.edit && <button className="editbtn" onClick={p.edit}>✎ Edit</button>}
        </div>
      </div>
      <div className="tvbody">
        <table><tbody>
          <tr><td>profile</td><td><Select label="Profile" value={profile} options={[["", "unassigned"], ...p.profiles.map((v): [string, string] => [v, v])]} /></td></tr>
          <tr><td>priority</td><td><Select label="Priority" value={priority} options={[["", "—"], ...PRIORITIES.map((v): [string, string] => [v, v])]} /></td></tr>
          <tr><td>labels</td><td><Chips values={labels} flag="needs-human" /></td></tr>
          <tr><td>milestone</td><td><Select label="Milestone" value={milestone} options={[["", "—"], ...p.milestones.map((v): [string, string] => [v, v])]} /></td></tr>
          <tr><td>depends on</td><td><Chips values={deps} /></td></tr>
          <tr className="ro"><td>pull requests</td><td>{task.prs.length ? task.prs.map((pr) => (
            <div key={pr.number}><a href={pr.url} target="_blank" rel="noopener">#{pr.number}</a> <span className="k">{pr.merged ? "merged" : pr.checks}{pr.threads ? `, ${pr.threads} open threads` : ""}</span></div>
          )) : "—"}</td></tr>
          <tr className="ro"><td>machine</td><td>{p.machine}</td></tr>
        </tbody></table>
        {p.refusal}
        {p.startNote}
        <section className="sec"><div className="sh"><span className="t">Description</span></div><Txt value={r?.description ?? task.description.split("\n## ")[0]} label="Description" /></section>
        {r && <Checks name="Acceptance criteria" items={r.acceptanceCriteria} />}
        {r && <Checks name="Definition of done" items={r.definitionOfDone} />}
        {r && <section className="sec"><div className="sh"><span className="t">Implementation plan</span></div><Txt value={r.plan} label="Implementation plan" long /></section>}
        {r && <section className="sec"><div className="sh"><span className="t">Notes</span></div><Txt value={r.notes} label="Notes" long /></section>}
      </div>
      <div className="tvfoot">
        <MoveMenu items={offered} saving={p.saving} move={p.move} />
        {startVisible && (
          <button className="startbtn" disabled={!startable(task) || p.saving} title={startable(task) ? undefined : task.moves.in_progress?.reason} onClick={p.start}>▶ Start session</button>
        )}
      </div>
    </div>
  );
}
