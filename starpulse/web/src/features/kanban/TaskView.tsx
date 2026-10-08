// The task view: every section reads in place and edits in place, one at a time, each Save a guarded write of that section's diff.
import { Fragment, useCallback, useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react";
import { ago, fmtAt } from "../../shared/clock";
import { columnsOf, type KanbanTask } from "./kanban";
import { startLane, startable } from "./start";
import { StartCriteria } from "./StartCriteria";
import type { Capabilities, Pull } from "../../api";
import {
  PRIORITIES, SECTION_NAMES, ciHistory, closesOnKey, copyText, copyToClipboard, dependencyRows, editKey, fetchRecord, markdown, menuKey, metCount, onScrim, saveSection, sessionOf, toggleItem,
  type CiPull, type DepRow, type Item, type MenuState, type Section, type TaskField, type TaskRecord,
} from "./taskView";

export interface TaskViewProps {
  task: KanbanTask;
  /** Every card on the board: the titles and lanes of the tasks this one depends on, and the tasks that depend on it. */
  tasks: KanbanTask[];
  record: TaskRecord | null;
  lane: string;
  /** The page's clock in epoch seconds, for the time in the lane and the ages in the rail. */
  now: number;
  profiles: string[];
  milestones: string[];
  refusal: ReactNode;
  startNote: ReactNode;
  /** The Waiting stack or Done chain the task sits in, listed in its own row. */
  stack?: ReactNode;
  capabilities?: Capabilities;
  names?: Record<string, string>;
  saving: boolean;
  claiming: boolean;
  close: () => void;
  /** Open another task's modal. */
  open: (id: string) => void;
  hide: () => void;
  constellation: () => void;
  move: (to: string) => void;
  start: () => void;
  archive?: () => void;
  onSaved?: (record: TaskRecord, changed: TaskField[]) => void;
  /** The section whose editor starts open: a deterministic entry state for the self-contained preview and static render tests. */
  initialEditing?: Section;
}

interface FieldProps { field: TaskField; editing: boolean; bad: boolean }
const fieldClass = (base: string, live: boolean, bad: boolean) => `${base}${live ? " live" : ""}${bad ? " bad" : ""}`;

function Txt({ value, label, className = "", long, focus, onChange, ...f }: FieldProps & {
  value: string; label: string; className?: string; long?: boolean; focus?: boolean; onChange: (value: string) => void;
}) {
  const el = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const t = el.current;
    if (!focus || !f.editing || !t) return;
    t.focus();
    t.setSelectionRange(t.value.length, t.value.length);
  }, [focus, f.editing]);
  const classes = fieldClass(`fv${long ? " long" : ""}${className && ` ${className}`}`, f.editing, f.bad);
  return <textarea ref={el} data-field={f.field} className={classes} rows={long ? 7 : 1} value={value} placeholder="—"
    aria-label={label} readOnly={!f.editing} tabIndex={f.editing || long ? 0 : -1} onChange={(e) => onChange(e.currentTarget.value)} />;
}

function Select({ value, options, label, onChange, ...f }: FieldProps & {
  value: string; options: [string, string][]; label: string; onChange: (value: string) => void;
}) {
  const known = options.some(([v]) => v === value) ? options : [...options, [value, value] as [string, string]];
  return (
    <select data-field={f.field} className={fieldClass("fv", true, f.bad)} aria-label={label} value={value}
      onChange={(e) => onChange(e.currentTarget.value)}>
      {known.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
  );
}

/** Labels in the rail's read table: a chip each, with the one that needs the operator highlighted. */
function ChipList({ values, flag }: { values: string[]; flag: string }) {
  return values.length ? <span className="chips">{values.map((v) => <span key={v} className={`chip${v === flag ? " nh" : ""}`}>{v}</span>)}</span> : <span className="k">—</span>;
}

const LanePill = ({ lane, name, small = false }: { lane: string; name: string; small?: boolean }) =>
  <span className={`tvlane${small ? " sm" : ""}`} data-lane={lane}><i />{name}</span>;

/** One section of the right rail: a small-caps heading with its count, the live state first. */
function RailSection({ name, count, children }: { name: string; count?: number | string; children: ReactNode }) {
  return <section className="sec rs"><div className="sh"><span className="t">{name}</span>{count ? <span className="n">{count}</span> : null}</div>{children}</section>;
}

/** The session that holds the task as a link that opens it in a new tab, or why none does. */
function SessionRows({ session, lane, startLane }: { session: ReturnType<typeof sessionOf>; lane: string; startLane: boolean }) {
  if (session) {
    return (
      <div className="session">
        <a href={session.url} target="_blank" rel="noopener" className="big"><span className="p" />Open the claiming session ↗</a>
        {session.line && <div className="k">{session.line}</div>}
      </div>
    );
  }
  return <div className="none">{lane === "in_progress" ? "No session has claimed it: worked by hand" : startLane ? "No session holds this task. ▶ Start session, top right, opens one." : "No session holds this task"}</div>;
}

const checkClass = (p: Pull) => (p.merged ? "merged" : p.checks === "failing" ? "fail" : p.checks);

function PullRows({ pulls }: { pulls: Pull[] }) {
  return pulls.length ? (
    <div className="prs">
      {pulls.map((p) => (
        <div key={p.number} className="pull">
          <a href={p.url} target="_blank" rel="noopener">#{p.number} ↗</a>
          <span className={`chk ${checkClass(p)}`}><i />{p.merged ? "merged" : `checks ${p.checks}`}</span>
          {p.threads ? <span className="thr">{p.threads} open thread{p.threads === 1 ? "" : "s"}</span> : <span className="k">no open threads</span>}
          {!p.merged && !!p.behind_main && <span className="thr">{p.behind_main} commit{p.behind_main === 1 ? "" : "s"} behind main</span>}
          {p.stale && <span className="thr">last read failed</span>}
        </div>
      ))}
    </div>
  ) : <span className="none">None yet</span>;
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** The four counts the D10 interview defined, in the order they happen to a pull request. */
function CiCounts({ c }: { c: Pick<CiPull, "runs" | "reruns" | "rebases" | "conflicts"> }) {
  return <>{[plural(c.runs, "run"), plural(c.reruns, "re-run"), plural(c.rebases, "rebase"), plural(c.conflicts, "conflict")]
    .map((text, i) => <span key={i} className={text.startsWith("0 ") ? "c z" : "c"}>{text}</span>)}</>;
}

/** The task's CI: its totals, then each pull request's counts and the state its trail left it in, blue when a third party moves the machine. */
function CiRows({ task }: { task: KanbanTask }) {
  const history = ciHistory(task);
  if (!history?.pulls.length) return <span className="none">{task.prs.length ? "No CI recorded yet" : "No pull request yet"}</span>;
  const mapped = task.machines.find((m) => m.machine === "ci")?.source;
  return (
    <div className="ci">
      {history.pulls.length > 1 && <div className="tot"><CiCounts c={history.total} /></div>}
      {history.pulls.map((p, i) => (
        <div key={i} className="cipull">
          {p.url ? <a href={p.url} target="_blank" rel="noopener">#{p.number} ↗</a> : <span className="k">pull request</span>}
          <span className={mapped ? "st mapped" : "st"} title={mapped ? `mapped from ${mapped}` : undefined}><i />{p.state.replace(/_/g, " ")}</span>
          <span className="cnt"><CiCounts c={p} /></span>
        </div>
      ))}
    </div>
  );
}

/** A dependency or a held task: its id, title and lane, opening that task's modal; a task off the board is only named. */
function DepRows({ rows, names, open }: { rows: DepRow[]; names: Record<string, string>; open: (id: string) => void }) {
  return rows.map((r) => r.lane === null ? (
    <div key={r.id} className="dep off"><span className="id">{r.id}</span><span className="tt">not on the board</span></div>
  ) : (
    <button key={r.id} className="dep" onClick={() => open(r.id)}><span className="id">{r.id}</span><span className="tt">{r.title}</span><LanePill lane={r.lane} name={names[r.lane] ?? r.lane} small /></button>
  ));
}

/** Each machine the task is in, closed to its state and open to its last five transitions. */
function MachineRows({ machines, now }: { machines: KanbanTask["machines"]; now: number }) {
  return machines.length ? (
    <div className="machs">
      {machines.map((m) => (
        <details key={m.machine} className="m">
          <summary><span className={m.source ? "p mapped" : "p"} title={m.source ? `mapped from ${m.source}` : undefined} /><b>{m.machine}</b><span className="s">{m.state.replace(/_/g, " ")}</span>
            <span className="k">{m.at ? `${ago(now - m.at)} ago` : ""}</span></summary>
          {m.trail.length > 0 && <ol>{m.trail.slice(-5).map((t, i) => <li key={i}><code>{t.event}</code> → {t.state.replace(/_/g, " ")}<span className="k"> {fmtAt(t.at)}</span></li>)}</ol>}
        </details>
      ))}
    </div>
  ) : <span className="none">In no machine right now</span>;
}

/** A section's description, plan or notes as Markdown blocks. */
function Md({ text, className = "md", drawn = false }: { text: string; className?: string; drawn?: boolean }) {
  return <div className={className}>{markdown(text, drawn).map((b, i) => b.kind === "h" ? <h4 key={i}>{b.text}</h4> : b.kind === "pre" ? <pre key={i}>{b.text}</pre> : <p key={i} className={b.kind === "moved" ? "moved" : undefined}>{b.text}</p>)}</div>;
}

interface ChecksProps {
  name: string; field: "acceptanceCriteria" | "definitionOfDone"; items: Item[]; editing: boolean; canToggle: boolean; bad: boolean;
  evidenceFor: number | null; evidence: Record<number, string>; tried: Set<number>;
  change: (items: Item[]) => void; toggle: (n: number, checked: boolean) => void; setEvidence: (n: number, value: string) => void;
}

/** A checklist: rows with a direct checkbox, or in its editor a growing text field and a ✕ per row. */
function Checks({ name, field, items, editing, canToggle, bad, evidenceFor, evidence, tried, change, toggle, setEvidence }: ChecksProps) {
  const word = field === "acceptanceCriteria" ? "criterion" : "item";
  if (!editing) {
    return (
      <div className="rlist">
        {items.length ? items.map((item) => (
          <Fragment key={item.n}>
            <label className={`ritem${item.checked ? " done" : ""}`}>
              <input type="checkbox" checked={item.checked} disabled={!canToggle} aria-label={`${name} #${item.n} done`}
                onChange={(e) => toggle(item.n, e.currentTarget.checked)} />
              <span className="nn">#{item.n}</span><span className="tx">{item.text}</span>
            </label>
            {evidenceFor === item.n && <label className={`evidence${tried.has(item.n) && !evidence[item.n]?.trim() ? " missing" : ""}`}>
              Evidence for #{item.n}<textarea autoFocus value={evidence[item.n] ?? ""} onChange={(e) => setEvidence(item.n, e.currentTarget.value)} />
            </label>}
          </Fragment>
        )) : <span className="none">—</span>}
      </div>
    );
  }
  return (
    <div className="list">
      {items.map((item, at) => (
        <div key={at} className="item">
          <span className="nn">{item.n ? `#${item.n}` : "new"}</span>
          <Txt field={field} editing bad={bad} value={item.text} label={`${name} #${item.n || "new"}`} focus={item.n === 0 || at === 0}
            onChange={(text) => change(items.map((old, i) => i === at ? { ...old, text } : old))} />
          <button className="remove" aria-label={`Remove ${name} #${item.n || "new"}`} onClick={() => change(items.filter((_, i) => i !== at))}>✕</button>
        </div>
      ))}
      <button className="add" onClick={() => change([...items, { n: 0, text: "", checked: false }])}>+ Add {word}</button>
    </div>
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

const CHECKLIST_FIELDS = ["acceptanceCriteria", "definitionOfDone"] as const;
const unnumbered = (r: TaskRecord) => CHECKLIST_FIELDS.some((field) => r[field].some((item) => !item.n));

export function TaskView(p: TaskViewProps) {
  const opened = p.record ?? fromSnapshot(p.task);
  const [editing, setEditing] = useState<Section | null>(p.record ? p.initialEditing ?? null : null);
  const [seenRecord, setSeenRecord] = useState(p.record);
  const [base, setBase] = useState<TaskRecord>(opened);
  const [draft, setDraft] = useState<TaskRecord>(opened);
  const [preview, setPreview] = useState(false);
  const [evidenceFor, setEvidenceFor] = useState<number | null>(null);
  const [evidence, setEvidence] = useState<Record<number, string>>({});
  const [tried, setTried] = useState<Set<number>>(new Set());
  const [invalid, setInvalid] = useState<Set<TaskField>>(new Set());
  const [writing, setWriting] = useState(false);
  const [writeRefusal, setWriteRefusal] = useState<{ reason: string; skill: string } | null>(null);
  const [toast, setToast] = useState("");
  const names = p.names ?? {};
  const canEdit = Boolean(p.capabilities?.edit && p.record);
  const change = (field: TaskField, value: TaskRecord[TaskField]) => {
    setDraft((record) => ({ ...record, [field]: value } as TaskRecord));
    setInvalid((fields) => { const next = new Set(fields); next.delete(field); return next; });
  };
  const fp = (field: TaskField, section: Section = field as Section): FieldProps => ({ field, editing: editing === section, bad: invalid.has(field) });

  // A record can arrive after the snapshot-sized modal opened. Adjust this form before that render completes.
  if (p.record !== seenRecord && !editing) {
    setSeenRecord(p.record);
    if (p.record) {
      setBase(p.record);
      setDraft(p.record);
    }
  }

  const clear = useCallback(() => {
    setEvidence({});
    setEvidenceFor(null);
    setTried(new Set());
    setInvalid(new Set());
    setWriteRefusal(null);
    setPreview(false);
  }, []);
  const edit = (section: Section) => {
    clear();
    setToast("");
    setDraft(base);
    setEditing(section);
  };
  const cancel = useCallback(() => {
    clear();
    setDraft(base);
    setEditing(null);
  }, [base, clear]);
  const commit = useCallback(async (section: Section, next: TaskRecord, notes: Record<number, string>) => {
    if (writing) return;
    setWriting(true);
    setWriteRefusal(null);
    const result = await saveSection(p.task.id, section, base, next, notes);
    setWriting(false);
    if (result.ok) {
      // an added row has no number until the board gives it one, so a later save would send it as new again
      const saved = result.changed.length && unnumbered(result.record) ? await fetchRecord(p.task.id) ?? result.record : result.record;
      clear();
      setBase(saved);
      setDraft(saved);
      setEditing(null);
      setToast(result.changed.length ? `✓ Saved ${SECTION_NAMES[section]}` : "Nothing changed");
      if (result.changed.length) p.onSaved?.(saved, result.changed);
    } else if ("missingEvidence" in result) {
      setTried(new Set(result.missingEvidence));
      setInvalid(new Set(["acceptanceCriteria"]));
    } else {
      setInvalid(new Set(result.fields));
      setWriteRefusal({ reason: result.reason, skill: result.skill });
    }
  }, [base, clear, p, writing]);
  const save = useCallback(() => { if (editing) void commit(editing, draft, evidence); }, [commit, draft, editing, evidence]);
  /** A checkbox writes at once, except a newly checked criterion, which first asks for its evidence under the item. */
  const toggle = (field: typeof CHECKLIST_FIELDS[number]) => (n: number, checked: boolean) => {
    const next = toggleItem(base, field, n, checked);
    clear();
    setToast("");
    setDraft(next);
    if (field === "acceptanceCriteria" && checked) {
      setEditing(field);
      setEvidenceFor(n);
      return;
    }
    setEditing(null);
    void commit(field, next, {});
  };

  useEffect(() => {
    if (!editing) return;
    const onKey = (event: KeyboardEvent) => {
      const action = editKey(event.key, event.ctrlKey, event.metaKey);
      if (!action) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (action === "save") save();
      else cancel();
    };
    addEventListener("keydown", onKey, true);
    return () => removeEventListener("keydown", onKey, true);
  }, [cancel, editing, save]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 2200);
    return () => clearTimeout(timer);
  }, [toast]);

  const criteria = base.start_criteria ?? [];
  const deps = dependencyRows(p.tasks, p.task);
  const offered = columnsOf(names).filter((c) => c in p.task.moves).map((c) => ({
    to: c, text: names[c] ?? c, allowed: p.task.moves[c].allowed, reason: p.task.moves[c].reason ?? "",
  }));
  const startVisible = startLane(p.task) && !p.claiming;
  const unavailable = p.saving || writing;
  const [copied, setCopied] = useState(false);
  const copy = () => void copyToClipboard(copyText(p.task, base.title)).then((ok) => {
    if (!ok) return;
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  });
  // the listener stays put while the modal is open: one swapped out mid-dispatch, as a host's redraw for an earlier listener would, never hears that key
  const closeOnKey = useEffectEvent((event: KeyboardEvent) => !event.defaultPrevented && closesOnKey(event.key, editing !== null) && p.close());
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => closeOnKey(event);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  const pen = (section: Section) => canEdit && editing !== section && (
    <button className="pen" title={`Edit ${SECTION_NAMES[section]}`} aria-label={`Edit ${SECTION_NAMES[section]}`} onClick={() => edit(section)}>✎ Edit</button>
  );
  const bar = (
    <div className="edbar">
      <span className="k">Ctrl+Enter saves · Esc cancels</span>
      <button className="cancelbtn" onClick={cancel}>Cancel</button>
      <button className="savebtn" disabled={writing} onClick={save}>Save</button>
    </div>
  );
  /** One editable section: its heading with the ✎, the body, and while it is the open one an outline and the bar. */
  const sec = (section: Section, name: string, body: ReactNode, count?: string, rail = false) => (
    <section className={`sec${rail ? " rs" : ""}${editing === section ? " on" : ""}`}>
      <div className="sh"><span className="t">{name}</span>{count && <span className="n">{count}</span>}{pen(section)}</div>
      {body}
      {editing === section && bar}
    </section>
  );
  const checks = (section: typeof CHECKLIST_FIELDS[number], name: string) => {
    const items = draft[section];
    return sec(section, name, <Checks name={name} field={section} items={items} editing={editing === section && evidenceFor === null} canToggle={canEdit && !writing} bad={invalid.has(section)}
      evidenceFor={editing === section ? evidenceFor : null} evidence={evidence} tried={tried} change={(value) => change(section, value)} toggle={toggle(section)}
      setEvidence={(n, value) => setEvidence((all) => ({ ...all, [n]: value }))} />, `${items.filter((i) => i.checked).length}/${items.length}`);
  };
  const prose = (section: "plan" | "notes", name: string) => sec(section, name, editing === section
    ? <Txt {...fp(section)} value={draft[section]} label={name} long focus onChange={(value) => change(section, value)} />
    : draft[section] ? <div className="md pre">{draft[section]}</div> : <span className="none">—</span>);
  const tab = (on: boolean, text: string) => <button role="tab" aria-selected={preview === on} className={preview === on ? "on" : ""} onClick={() => setPreview(on)}>{text}</button>;

  return (
    <div id="kbm" onClick={(event) => onScrim(event.target, event.currentTarget) && p.close()}>
      <div className="modal tv" role="dialog" aria-label={`${p.task.id} ${base.title}`} aria-busy={!p.record}>
        <div className="tvhead">
          <div className="tvmeta">
            <span className="tid">{p.task.id}</span>
            <button className={`copybtn${copied ? " ok" : ""}`} title={`Copy “${copyText(p.task, base.title)}”`} aria-label="Copy id and title" onClick={copy}>
              <span className="g">⧉</span>{copied ? "Copied" : "Copy"}
            </button>
            <LanePill lane={p.task.lane} name={p.lane} />
            {p.saving && <span className="k">saving</span>}
            <a href="/" onClick={(e) => { e.preventDefault(); p.constellation(); }}>Open in Star Map ↗</a>
            <div className="acts">
              {startVisible && <button className="startbtn" disabled={!startable(p.task) || unavailable}
                title={startable(p.task) ? undefined : p.task.moves.in_progress?.reason}
                onClick={p.start}>▶ Start session</button>}
              <MoveMenu items={offered} disabled={unavailable} move={p.move} />
              <button className="hidebtn" onClick={p.hide}>Hide task</button>
              {p.capabilities?.archive && <button className="archbtn" onClick={p.archive}>Archive…</button>}
              <button className="tvx" onClick={p.close} aria-label="Close">✕</button>
            </div>
          </div>
          <div className={`titlerow${editing === "title" ? " on" : ""}`}>
            <Txt {...fp("title")} value={draft.title} label="Title" className="title" focus onChange={(value) => change("title", value)} />
            {pen("title")}
            {editing === "title" && bar}
          </div>
        </div>
        <div className="tvbody">
          <div className="tvcol tvleft">
            {writeRefusal && <div className="editrefusal"><b>Save refused.</b> {writeRefusal.reason}{writeRefusal.skill && <div>Required skill: <code>{writeRefusal.skill}</code></div>}</div>}
            {sec("description", "Description", editing === "description" ? <>
              <div className="tabs" role="tablist">{tab(false, "Write")}{tab(true, "Preview")}<span className="k">Markdown</span></div>
              {preview ? <Md text={draft.description} className="md prev" drawn={criteria.length > 0} /> : <Txt {...fp("description")} value={draft.description} label="Description" long focus onChange={(value) => change("description", value)} />}
            </> : <Md text={draft.description} drawn={criteria.length > 0} />)}
            {p.record && checks("acceptanceCriteria", "Acceptance criteria")}
            {p.record && checks("definitionOfDone", "Definition of done")}
            {p.record && prose("plan", "Implementation plan")}
            {p.record && prose("notes", "Notes")}
          </div>
          <div className="tvcol tvrail">
            {p.refusal}
            {p.startNote}
            <RailSection name="Status">
              <div className="row"><LanePill lane={p.task.lane} name={p.lane} small />{p.task.entered > 0 && <span className="k">{`for ${ago(p.now - p.task.entered)}`}</span>}</div>
              {p.stack && <table className="props"><tbody><tr className="ro"><td>{p.task.lane === "done" ? "done chain" : "waiting stack"}</td><td className="stacklist">{p.stack}</td></tr></tbody></table>}
            </RailSection>
            <RailSection name="Session"><SessionRows session={sessionOf(p.task, p.record, p.now, startLane(p.task))} lane={p.task.lane} startLane={startLane(p.task)} /></RailSection>
            {criteria.length > 0 && <RailSection name="Start Criteria" count={`${metCount(criteria)}/${criteria.length} met`}><StartCriteria criteria={criteria} now={p.now} /></RailSection>}
            <RailSection name="Pull requests" count={p.task.prs.length}><PullRows pulls={p.task.prs} /></RailSection>
            <RailSection name="CI history" count={ciHistory(p.task)?.pulls.length}><CiRows task={p.task} /></RailSection>
            <RailSection name="Dependencies" count={deps.dependsOn.length + deps.holds.length + deps.more}>
              <div className="deps">
                <div className="lb">Depends on</div>
                {deps.dependsOn.length ? <DepRows rows={deps.dependsOn} names={names} open={p.open} /> : <span className="none">—</span>}
                {deps.holds.length > 0 && <>
                  <div className="lb">Holds</div>
                  <DepRows rows={deps.holds} names={names} open={p.open} />
                  {deps.more > 0 && <div className="k">+{deps.more} more</div>}
                </>}
              </div>
            </RailSection>
            <RailSection name="Machines" count={p.task.machines.length}><MachineRows machines={p.task.machines} now={p.now} /></RailSection>
            {sec("details", "Details", (
              <table className="props"><tbody>
                <tr><td>profile</td><td>{editing === "details" ? <Select {...fp("profile", "details")} label="Profile" value={draft.profile} options={[["", "unassigned"], ...p.profiles.map((v): [string, string] => [v, v])]} onChange={(value) => change("profile", value)} /> : draft.profile || "—"}</td></tr>
                <tr><td>priority</td><td>{editing === "details" ? <Select {...fp("priority", "details")} label="Priority" value={priorityValue(draft.priority)} options={[["", "—"], ...PRIORITIES.map((v): [string, string] => [v, v])]} onChange={(value) => change("priority", value)} /> : priorityValue(draft.priority) || "—"}</td></tr>
                <tr><td>labels</td><td><ChipList values={draft.labels} flag="needs-human" /></td></tr>
                <tr><td>milestone</td><td>{editing === "details" ? <Select {...fp("milestone", "details")} label="Milestone" value={draft.milestone} options={[["", "—"], ...p.milestones.map((v): [string, string] => [v, v])]} onChange={(value) => change("milestone", value)} /> : draft.milestone || "—"}</td></tr>
                <tr><td>created</td><td><span className="k">{p.task.created ? `${ago(p.now - p.task.created)} ago` : "—"}</span></td></tr>
              </tbody></table>
            ), undefined, true)}
          </div>
        </div>
        {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    </div>
  );
}
