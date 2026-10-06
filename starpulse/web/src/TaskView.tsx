// The task view: the same framed fields in read and edit mode, with one guarded write for the complete diff.
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { columnsOf, type KanbanTask } from "./kanban";
import { startLane, startable } from "./start";
import type { Capabilities } from "./types";
import {
  PRIORITIES, changedFields, discardMessage, editKey, menuKey, newlyChecked, saveTask,
  type Item, type MenuState, type TaskField, type TaskRecord,
} from "./taskView";

export interface TaskViewProps {
  task: KanbanTask;
  record: TaskRecord | null;
  lane: string;
  machine: string;
  profiles: string[];
  milestones: string[];
  refusal: ReactNode;
  startNote: ReactNode;
  capabilities?: Capabilities;
  names?: Record<string, string>;
  saving: boolean;
  claiming: boolean;
  close: () => void;
  hide: () => void;
  constellation: () => void;
  move: (to: string) => void;
  start: () => void;
  archive?: () => void;
  onSaved?: (record: TaskRecord, changed: TaskField[]) => void;
  /** A deterministic entry state for the self-contained preview and static render tests. */
  initialEditing?: boolean;
}

interface FieldProps { field: TaskField; editing: boolean; dirty: boolean; bad: boolean }
const fieldClass = (base: string, dirty: boolean, bad: boolean) => `${base}${dirty ? " dirty" : ""}${bad ? " bad" : ""}`;

function Txt({ value, label, className = "", long, onChange, ...f }: FieldProps & {
  value: string; label: string; className?: string; long?: boolean; onChange: (value: string) => void;
}) {
  const el = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const t = el.current;
    if (!t || long) return;
    t.style.height = "auto";
    t.style.height = `${t.scrollHeight + 2}px`;
  }, [value, long]);
  const classes = fieldClass(`fv${long ? " long" : ""}${className && ` ${className}`}`, f.dirty, f.bad);
  return <textarea ref={el} data-field={f.field} className={classes} rows={long ? 7 : 1} value={value} placeholder="—"
    aria-label={label} readOnly={!f.editing} tabIndex={f.editing || long ? 0 : -1} onChange={(e) => onChange(e.currentTarget.value)} />;
}

function Select({ value, options, label, onChange, ...f }: FieldProps & {
  value: string; options: [string, string][]; label: string; onChange: (value: string) => void;
}) {
  const known = options.some(([v]) => v === value) ? options : [...options, [value, value] as [string, string]];
  return (
    <select data-field={f.field} className={fieldClass("fv", f.dirty, f.bad)} aria-label={label} value={value}
      disabled={!f.editing} onChange={(e) => onChange(e.currentTarget.value)}>
      {known.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
  );
}

function Chips({ values, flag, label, onChange, ...f }: FieldProps & {
  values: string[]; flag?: string; label: string; onChange: (values: string[]) => void;
}) {
  return (
    <div data-field={f.field} className={fieldClass("fv chips", f.dirty, f.bad)}>
      {f.editing ? (
        <input className="chipinput" value={values.join(", ")} aria-label={label}
          onChange={(e) => onChange(e.currentTarget.value.split(",").map((v) => v.trim()).filter(Boolean))} />
      ) : values.length ? values.map((v) => <span key={v} className={`chip${v === flag ? " nh" : ""}`}>{v}</span>) : <span className="none">—</span>}
    </div>
  );
}

function Checks({ name, field, items, base, editing, dirty, bad, evidence, tried, change, setEvidence }: {
  name: string; field: "acceptanceCriteria" | "definitionOfDone"; items: Item[]; base: Item[]; editing: boolean; dirty: boolean; bad: boolean;
  evidence: Record<number, string>; tried: Set<number>; change: (items: Item[]) => void; setEvidence: (n: number, value: string) => void;
}) {
  const was = new Map(base.map((item) => [item.n, item.checked]));
  const update = (at: number, item: Item) => change(items.map((old, i) => i === at ? item : old));
  const add = () => change([...items, { n: Math.max(0, ...items.map((item) => item.n)) + 1, text: "", checked: false }]);
  return (
    <section className="sec">
      <div className="sh"><span className="t">{name}</span><span className="n">{items.filter((i) => i.checked).length}/{items.length}</span></div>
      <div className="list">
        {items.map((item, at) => {
          const needsEvidence = field === "acceptanceCriteria" && item.checked && !was.get(item.n);
          return (
            <div key={item.n} className={`item${item.checked ? " done" : ""}`}>
              <input type="checkbox" checked={item.checked} disabled={!editing} aria-label={`${name} #${item.n} done`}
                onChange={(e) => update(at, { ...item, checked: e.currentTarget.checked })} />
              <input type="text" data-field={field} className={fieldClass("fv", dirty, bad)} value={item.text}
                readOnly={!editing} tabIndex={editing ? 0 : -1} aria-label={`${name} #${item.n}`}
                onChange={(e) => update(at, { ...item, text: e.currentTarget.value })} />
              <button className="remove" aria-label={`Remove ${name} #${item.n}`} aria-hidden={!editing} disabled={!editing}
                onClick={() => change(items.filter((_, i) => i !== at))}>−</button>
              {needsEvidence && <label className={`evidence${tried.has(item.n) && !evidence[item.n]?.trim() ? " missing" : ""}`}>
                Evidence for #{item.n}<textarea value={evidence[item.n] ?? ""} onChange={(e) => setEvidence(item.n, e.currentTarget.value)} />
              </label>}
            </div>
          );
        })}
        <button className="add" aria-hidden={!editing} disabled={!editing} onClick={add}>+ Add {field === "acceptanceCriteria" ? "criterion" : "item"}</button>
      </div>
    </section>
  );
}

const SHUT: MenuState = { open: false, on: -1 };

function MoveMenu({ items, disabled, move }: { items: { to: string; text: string; allowed: boolean; reason: string }[]; disabled: boolean; move: (to: string) => void }) {
  const [menu, setMenu] = useState<MenuState>(SHUT);
  const enabled = items.map(() => !disabled);
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
          <div key={it.to} role="menuitem" className={`${it.allowed ? "ok" : "guard"}${i === menu.on ? " on" : ""}`} aria-disabled={disabled} title={it.allowed ? undefined : it.reason}
            onMouseMove={() => setMenu({ open: true, on: i })} onClick={(e) => { e.stopPropagation(); if (!disabled) pick(i); }}>
            <span className="g">{it.allowed ? "→" : "⊘"}</span>{it.text}
          </div>
        ))}
      </div>
      <button className="mvbtn" aria-haspopup="menu" aria-expanded={menu.open} disabled={disabled || !items.length}
        title={disabled ? "Finish editing before moving this task" : items.length ? undefined : "no moves from here"}
        onClick={() => setMenu(menu.open ? SHUT : { open: true, on: 0 })}>Move to</button>
    </div>
  );
}

const fromSnapshot = (task: KanbanTask): TaskRecord => ({
  title: task.title, profile: task.assignee, priority: "", labels: task.labels, milestone: task.milestone,
  dependencies: task.dependencies, description: task.description.split("\n## ")[0], plan: "", notes: "",
  acceptanceCriteria: [], definitionOfDone: [],
});
const priorityValue = (value: string) => PRIORITIES.find((v) => v.toLowerCase() === value.toLowerCase()) ?? value;

export function TaskView(p: TaskViewProps) {
  const opened = p.record ?? fromSnapshot(p.task);
  const [editing, setEditing] = useState(Boolean(p.initialEditing && p.record));
  const [seenRecord, setSeenRecord] = useState(p.record);
  const [base, setBase] = useState<TaskRecord>(opened);
  const [draft, setDraft] = useState<TaskRecord>(opened);
  const [evidence, setEvidence] = useState<Record<number, string>>({});
  const [tried, setTried] = useState<Set<number>>(new Set());
  const [invalid, setInvalid] = useState<Set<TaskField>>(new Set());
  const [writing, setWriting] = useState(false);
  const [writeRefusal, setWriteRefusal] = useState<{ reason: string; skill: string } | null>(null);
  const [saved, setSaved] = useState("");
  const [discard, setDiscard] = useState<"cancel" | "close" | null>(null);
  const diff = changedFields(base, draft);
  const dirty = new Set(diff.fields);
  const names = p.names ?? {};
  const change = (field: TaskField, value: TaskRecord[TaskField]) => {
    setDraft((record) => ({ ...record, [field]: value } as TaskRecord));
    setInvalid((fields) => { const next = new Set(fields); next.delete(field); return next; });
    setSaved("");
  };
  const fp = (field: TaskField): FieldProps => ({ field, editing, dirty: dirty.has(field), bad: invalid.has(field) });

  // A record can arrive after the snapshot-sized modal opened. Adjust this form before that render completes.
  if (p.record !== seenRecord && !editing) {
    setSeenRecord(p.record);
    if (p.record) {
      setBase(p.record);
      setDraft(p.record);
    }
  }

  const beginEdit = () => {
    if (!p.record) return;
    setBase(p.record);
    setDraft(p.record);
    setEvidence({});
    setTried(new Set());
    setInvalid(new Set());
    setWriteRefusal(null);
    setSaved("");
    setEditing(true);
  };
  const cancelEdit = useCallback(() => {
    setDraft(base);
    setEditing(false);
    setDiscard(null);
    setWriteRefusal(null);
    setInvalid(new Set());
  }, [base]);
  const askLeave = useCallback((after: "cancel" | "close") => {
    if (diff.fields.length) return setDiscard(after);
    if (after === "close") p.close();
    else cancelEdit();
  }, [cancelEdit, diff.fields.length, p]);
  const confirmDiscard = () => {
    const after = discard;
    cancelEdit();
    if (after === "close") p.close();
  };
  const save = useCallback(async () => {
    if (!editing || writing) return;
    setWriting(true);
    setWriteRefusal(null);
    const result = await saveTask(p.task.id, base, draft, evidence);
    setWriting(false);
    if (result.ok) {
      const labels = result.changed.join(", ");
      setBase(result.record);
      setDraft(result.record);
      setEditing(false);
      setInvalid(new Set());
      setSaved(`Saved ${result.changed.length} field${result.changed.length === 1 ? "" : "s"}${labels ? ` (${labels})` : ""}`);
      p.onSaved?.(result.record, result.changed);
    } else if ("missingEvidence" in result) {
      setTried(new Set(result.missingEvidence));
      setInvalid(new Set(["acceptanceCriteria"]));
    } else {
      setInvalid(new Set(result.fields));
      setWriteRefusal({ reason: result.reason, skill: result.skill });
    }
  }, [base, draft, editing, evidence, p, writing]);

  useEffect(() => {
    if (!editing) return;
    const onKey = (event: KeyboardEvent) => {
      const action = editKey(event.key, event.ctrlKey, event.metaKey, diff.fields.length > 0);
      if (!action) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (action === "save") void save();
      else if (action === "discard") setDiscard("cancel");
      else cancelEdit();
    };
    addEventListener("keydown", onKey, true);
    return () => removeEventListener("keydown", onKey, true);
  }, [cancelEdit, diff.fields.length, editing, save]);

  const offered = columnsOf(names).filter((c) => c in p.task.moves).map((c) => ({
    to: c, text: names[c] ?? c, allowed: p.task.moves[c].allowed, reason: p.task.moves[c].reason,
  }));
  const startVisible = startLane(p.task) && !p.claiming;
  const unavailable = editing || p.saving || writing;
  const checked = new Set(newlyChecked(base, draft));

  return (
    <div id="kbm" onClick={(event) => event.target === event.currentTarget && (editing ? askLeave("close") : p.close())}>
      <div className={`modal tv${editing ? " editing" : ""}`} role="dialog" aria-label={p.task.id}>
        <button className="x" onClick={() => editing ? askLeave("close") : p.close()} aria-label="Close">✕</button>
        <div className="tvhead">
          <div className="ttl">
            <Txt {...fp("title")} value={draft.title} label="Title" className="title" onChange={(value) => change("title", value)} />
            <div className="k">{p.task.id} · {p.lane}{p.saving ? " · saving" : ""} · <a href="/" onClick={(e) => { e.preventDefault(); p.constellation(); }}>Open in Star Map ↗</a></div>
          </div>
          <div className="acts">
            {editing ? <>
              <span className="changed">{diff.fields.length} field{diff.fields.length === 1 ? "" : "s"} changed</span>
              <button className="cancelbtn" onClick={() => askLeave("cancel")}>Cancel <kbd>Esc</kbd></button>
              <button className="savebtn" disabled={writing || !diff.fields.length} onClick={() => void save()}>Save <kbd>Ctrl+Enter</kbd></button>
            </> : <>
              <button className="hidebtn" onClick={p.hide}>Hide task</button>
              {p.capabilities?.archive && <button className="archbtn" onClick={p.archive}>Archive…</button>}
              {p.capabilities?.edit && p.record && <button className="editbtn" onClick={beginEdit}>✎ Edit</button>}
            </>}
          </div>
        </div>
        <div className="tvbody">
          {saved && <div className="saveok">✓ {saved}</div>}
          {writeRefusal && <div className="editrefusal"><b>Save refused.</b> {writeRefusal.reason}{writeRefusal.skill && <div>Required skill: <code>{writeRefusal.skill}</code></div>}</div>}
          <table><tbody>
            <tr><td>profile</td><td><Select {...fp("profile")} label="Profile" value={draft.profile} options={[["", "unassigned"], ...p.profiles.map((v): [string, string] => [v, v])]} onChange={(value) => change("profile", value)} /></td></tr>
            <tr><td>priority</td><td><Select {...fp("priority")} label="Priority" value={priorityValue(draft.priority)} options={[["", "—"], ...PRIORITIES.map((v): [string, string] => [v, v])]} onChange={(value) => change("priority", value)} /></td></tr>
            <tr><td>labels</td><td><Chips {...fp("labels")} values={draft.labels} flag="needs-human" label="Labels" onChange={(value) => change("labels", value)} /></td></tr>
            <tr><td>milestone</td><td><Select {...fp("milestone")} label="Milestone" value={draft.milestone} options={[["", "—"], ...p.milestones.map((v): [string, string] => [v, v])]} onChange={(value) => change("milestone", value)} /></td></tr>
            <tr><td>depends on</td><td><Chips {...fp("dependencies")} values={draft.dependencies} label="Dependencies" onChange={(value) => change("dependencies", value)} /></td></tr>
            <tr className="ro"><td>pull requests</td><td>{p.task.prs.length ? p.task.prs.map((pr) => (
              <div key={pr.number}><a href={pr.url} target="_blank" rel="noopener">#{pr.number}</a> <span className="k">{pr.merged ? "merged" : pr.checks}{pr.threads ? `, ${pr.threads} open threads` : ""}</span></div>
            )) : "—"}</td></tr>
            <tr className="ro"><td>machine</td><td>{p.machine}</td></tr>
          </tbody></table>
          {p.refusal}
          {p.startNote}
          <section className="sec"><div className="sh"><span className="t">Description</span></div><Txt {...fp("description")} value={draft.description} label="Description" onChange={(value) => change("description", value)} /></section>
          {p.record && <Checks name="Acceptance criteria" field="acceptanceCriteria" items={draft.acceptanceCriteria} base={base.acceptanceCriteria}
            editing={editing} dirty={dirty.has("acceptanceCriteria")} bad={invalid.has("acceptanceCriteria")} evidence={evidence} tried={tried}
            change={(value) => change("acceptanceCriteria", value)} setEvidence={(n, value) => setEvidence((all) => ({ ...all, [n]: value }))} />}
          {p.record && <Checks name="Definition of done" field="definitionOfDone" items={draft.definitionOfDone} base={base.definitionOfDone}
            editing={editing} dirty={dirty.has("definitionOfDone")} bad={invalid.has("definitionOfDone")} evidence={{}} tried={new Set()}
            change={(value) => change("definitionOfDone", value)} setEvidence={() => {}} />}
          {p.record && <section className="sec"><div className="sh"><span className="t">Implementation plan</span></div><Txt {...fp("plan")} value={draft.plan} label="Implementation plan" long onChange={(value) => change("plan", value)} /></section>}
          {p.record && <section className="sec"><div className="sh"><span className="t">Notes</span></div><Txt {...fp("notes")} value={draft.notes} label="Notes" long onChange={(value) => change("notes", value)} /></section>}
          {editing && checked.size > 0 && <div className="evidence-note">Evidence is required for each newly checked acceptance criterion before Save.</div>}
        </div>
        <div className="tvfoot">
          <MoveMenu items={offered} disabled={unavailable} move={p.move} />
          {startVisible && <button className="startbtn" disabled={!startable(p.task) || unavailable}
            title={editing ? "Finish editing before starting a session" : startable(p.task) ? undefined : p.task.moves.in_progress?.reason}
            onClick={p.start}>▶ Start session</button>}
        </div>
        {discard && <div className="discard" role="alertdialog" aria-label="Discard changes">
          <div><b>{discardMessage(diff.fields.length)}</b><p>Your edits have not been saved.</p></div>
          <div className="discardacts"><button onClick={() => setDiscard(null)}>Keep editing</button><button className="danger" onClick={confirmDiscard}>Discard</button></div>
        </div>}
      </div>
    </div>
  );
}
