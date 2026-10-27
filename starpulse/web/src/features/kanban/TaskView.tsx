// The task view: every section reads in place and edits in place, one at a time, each Save a guarded write of that section's diff.
import { Fragment, useCallback, useEffect, useEffectEvent, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { ago, fmtAt } from "../../shared/clock";
import { usePhone } from "../../shared/usePhone";
import { RatingControl } from "./RatingControl";
import { columnsOf, prReadState, roleOf, type KanbanTask } from "./kanbanModel";
import { startLane, startable } from "./start";
import { StartCriteria } from "./StartCriteria";
import { DocReader, DocRows, useDocs } from "./DocReader";
import { Inline, Md } from "./Markdown";
import { sessionNickname } from "./nickname";
import type { Capabilities, Pull, Roles } from "../../api";
import {
  LABEL_FIELDS, LABEL_RULE, PRIORITIES, SECTION_NAMES, ciHistory, closesOnKey, copyText, copyToClipboard, dependencyRows, detailFields, editKey, fetchRecord, labelRuleError, menuKey, metCount, onScrim, postComment, saveSection, sessionOf, setDetailField, taskActivity, taskBody, toggleItem,
  type ActivityEvent, type CiPull, type DepRow, type DocLink, type Item, type LabelField, type MenuState, type Section, type TaskField, type TaskRecord,
} from "./taskViewModel";

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
  /** Why the full record is missing, once its read failed: the modal is no longer busy waiting for it. */
  readNote?: ReactNode;
  /** The Waiting stack or Done chain the task sits in, listed in its own row. */
  stack?: ReactNode;
  capabilities?: Capabilities;
  names?: Record<string, string>;
  /** Which State plays which part, as the snapshot publishes it: the part, never the State's id, decides what the view offers. */
  roles: Roles;
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

/** A free-form label, with a × to remove it while Details is open; the read table lists them as a ChipList. */
const Chip = ({ value, remove }: { value: string; remove?: (value: string) => void }) =>
  <span className="chip">{value}{remove && <button className="x" aria-label={`Remove ${value}`} onClick={() => remove(value)}>×</button>}</span>;
const ChipList = ({ values }: { values: string[] }) =>
  values.length ? <span className="chips">{values.map((v) => <Chip key={v} value={v} />)}</span> : <span className="k">—</span>;

const LanePill = ({ lane, role, name, small = false }: { lane: string; role?: string; name: string; small?: boolean }) =>
  <span className={`tvlane${small ? " sm" : ""}`} data-lane={lane} data-role={role}><i />{name}</span>;

/** One section of the right rail: a small-caps heading with its count, the live state first. */
function RailSection({ name, count, children }: { name: string; count?: number | string; children: ReactNode }) {
  return <section className="sec rs"><div className="sh"><span className="t">{name}</span>{count ? <span className="n">{count}</span> : null}</div>{children}</section>;
}

/** The session that holds the task as a link that opens it in a new tab, or why none does. */
function SessionRows({ session, assignee, worked, startLane }: { session: ReturnType<typeof sessionOf>; assignee: string; worked: boolean; startLane: boolean }) {
  if (session) {
    return (
      <div className="session">
        <a href={session.url} target="_blank" rel="noopener" className="big"><span className="p" />Open the claiming session ↗</a>
        <dl className="who2">
          {assignee && <><dt>Assignee</dt><dd>{sessionNickname(assignee) ?? assignee}</dd></>}
          <dt>Session</dt>
          <dd><code>{session.id.slice(0, 8)}</code><button type="button" className="mini" title="Copy the resume command" onClick={() => void copyToClipboard(`claude --resume ${session.id}`)}>⧉ resume</button></dd>
        </dl>
        {session.line && <div className="k">{session.line}</div>}
      </div>
    );
  }
  return <div className="none">{worked ?"No session has claimed it: worked by hand" : startLane ? "No session holds this task. ▶ Start session, top right, opens one." : "No session holds this task"}</div>;
}

/** A run's ISO start in Arizona time, or a dash when the scheduler gave none it can parse. */
const runStart = (iso: string) => (Number.isNaN(Date.parse(iso)) ? "—" : fmtAt(Date.parse(iso) / 1000));

/** A task carrying a label with this prefix is a deviated sample: its run drew a profile off the matrix, so the operator rates it. */
const TRIAL = "trial-";

const checkClass = (p: Pull) => (p.merged ? "merged" : p.checks === "failing" ? "fail" : p.checks);

/** One pull request's row: its state, check result and unread review count, or "not read yet" with the reason; `ci` is its CI line. */
function PullRow({ p, ci }: { p: Pull; ci?: ReactNode }) {
  const read = prReadState(p);
  return (
    <div className="pull">
      <a href={p.url} target="_blank" rel="noopener">{p.repo}#{p.number} ↗</a>
      {read.read ? (
        <>
          <span className={`chk ${checkClass(p)}`}><i />{read.state === "merged" ? "merged" : `checks ${read.checks}`}</span>
          {read.unreviewed > 0 && <span className="rd">{plural(read.unreviewed, "unread review")}</span>}
        </>
      ) : (
        <>
          <span className="chk unread"><i />{read.label}</span>
          <span className="rd">{read.reason}</span>
        </>
      )}
      {ci}
    </div>
  );
}

/** A rail list that scrolls inside a capped height, fading its lower edge until the last row is in view. */
function Box({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const fade = useCallback(() => {
    const box = ref.current;
    if (box) box.classList.toggle("end", box.scrollTop + box.clientHeight >= box.scrollHeight - 2);
  }, []);
  useEffect(fade);
  return <div ref={ref} className="box" onScroll={fade}>{children}</div>;
}

const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? "" : "s"}`;

/** The four counts the D10 interview defined, in the order they happen to a pull request. */
function CiCounts({ c }: { c: Pick<CiPull, "runs" | "reruns" | "rebases" | "conflicts"> }) {
  return <>{[plural(c.runs, "run"), plural(c.reruns, "re-run"), plural(c.rebases, "rebase"), plural(c.conflicts, "conflict")]
    .map((text, i) => <span key={i} className={text.startsWith("0 ") ? "c z" : "c"}>{text}</span>)}</>;
}

/** A pull request's CI: the state its trail left it in, blue when a third party moves the machine, then its counts. */
function CiLine({ c, mapped }: { c: CiPull; mapped?: string | null }) {
  return (
    <div className="ci">
      <span className={mapped ? "st mapped" : "st"} title={mapped ? `mapped from ${mapped}` : undefined}><i />{c.state.replace(/_/g, " ")}</span>
      <span className="cnt"><CiCounts c={c} /></span>
    </div>
  );
}

/** The task's pull requests, each with its CI line, under the task's CI totals when it has two or more; a CI entry no pull request matches is its own row. */
function PullRows({ task }: { task: KanbanTask }) {
  const history = ciHistory(task);
  const mapped = task.machines.find((m) => m.machine === "ci")?.source;
  const ciOf = new Map((history?.pulls ?? []).map((c) => [c.number, c]));
  const unmatched = (history?.pulls ?? []).filter((c) => !task.prs.some((p) => p.number === c.number));
  if (!task.prs.length && !unmatched.length) return <span className="none">None yet</span>;
  const line = (c: CiPull | undefined) => c && <CiLine c={c} mapped={mapped} />;
  return (
    <>
      {history && history.pulls.length > 1 && <div className="tot"><CiCounts c={history.total} /></div>}
      <Box>
        <div className="prs">
          {task.prs.map((p) => <PullRow key={`${p.repo}#${p.number}`} p={p} ci={line(ciOf.get(p.number))} />)}
          {unmatched.map((c, i) => <div key={i} className="pull"><span className="k">pull request</span>{line(c)}</div>)}
        </div>
      </Box>
    </>
  );
}

/** A dependency or a held task: its id, title and lane, opening that task's modal; a task off the board is only named. */
function DepRows({ rows, names, roles, open }: { rows: DepRow[]; names: Record<string, string>; roles: Roles; open: (id: string) => void }) {
  return rows.map((r) => r.lane === null ? (
    <div key={r.id} className="dep off"><span className="id">{r.id}</span><span className="tt">not on the board</span></div>
  ) : (
    <button key={r.id} className="dep" onClick={() => open(r.id)}><span className="id">{r.id}</span><span className="tt">{r.title}</span><LanePill lane={r.lane} role={roleOf(roles, r.lane)} name={names[r.lane] ?? r.lane} small /></button>
  ));
}

interface ChecksProps {
  name: string; field: "acceptanceCriteria" | "definitionOfDone"; items: Item[]; editing: boolean; canToggle: boolean; bad: boolean;
  evidenceFor: number | null; evidence: Record<number, string>; tried: Set<number>;
  change: (items: Item[]) => void; toggle: (n: number, checked: boolean) => void; setEvidence: (n: number, value: string) => void; open: (id: string) => void;
}

/** A checklist: rows with a direct checkbox, or in its editor a growing text field and a ✕ per row. */
function Checks({ name, field, items, editing, canToggle, bad, evidenceFor, evidence, tried, change, toggle, setEvidence, open }: ChecksProps) {
  const word = field === "acceptanceCriteria" ? "criterion" : "item";
  if (!editing) {
    return (
      <div className="rlist">
        {items.length ? items.map((item) => (
          <Fragment key={item.n}>
            <label className={`ritem${item.checked ? " done" : ""}`} id={field === "acceptanceCriteria" ? `ac${item.n}` : undefined}>
              <input type="checkbox" checked={item.checked} disabled={!canToggle} aria-label={`${name} #${item.n} done`}
                onChange={(e) => toggle(item.n, e.currentTarget.checked)} />
              <span className="nn">#{item.n}</span><span className="tx"><Inline text={item.text} open={open} /></span>
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
            onMouseMove={() => setMenu((m) => m.open && m.on === i ? m : { open: true, on: i })} onClick={(e) => { e.stopPropagation(); if (!disabled) pick(i); }}>
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
  title: task.title, profile: task.profile ?? "", priority: "", labels: task.labels, milestone: task.milestone,
  dependencies: task.dependencies, description: task.description.split("\n## ")[0], plan: "", notes: "",
  acceptanceCriteria: [], definitionOfDone: [],
});
const priorityValue = (value: string) => PRIORITIES.find((v) => v.toLowerCase() === value.toLowerCase()) ?? value;

const CHECKLIST_FIELDS = ["acceptanceCriteria", "definitionOfDone"] as const;
const unnumbered = (r: TaskRecord) => CHECKLIST_FIELDS.some((field) => r[field].some((item) => !item.n));

export function TaskView(p: TaskViewProps) {
  const phone = usePhone();
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
  const [pending, setPending] = useState("");
  const [labelRefusal, setLabelRefusal] = useState("");
  const [comment, setComment] = useState("");
  const [posting, setPosting] = useState(false);
  const [reading, setReading] = useState<{ task: string; doc: DocLink } | null>(null);
  const docs = useDocs(opened);
  const readDoc = reading?.task === p.task.id ? reading.doc : null;
  const names = p.names ?? {};
  const { roles } = p;
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
    setPending("");
    setLabelRefusal("");
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
      // a refused label draws under Add label, where the operator can fix it
      if (section === "details" && result.fields.includes("labels")) setLabelRefusal(result.reason);
      else setWriteRefusal({ reason: result.reason, skill: result.skill });
    }
  }, [base, clear, p, writing]);
  const typed = pending.trim();
  const typedError = typed ? labelRuleError(typed) || (draft.labels.includes(typed) ? `"${typed}" is already on this task.` : "") : "";
  const addLabel = () => {
    if (!typed || typedError) return;
    change("labels", [...draft.labels, typed]);
    setPending("");
  };
  /** A label typed but not yet added is added by the save, once it passes the rule. */
  const save = useCallback(() => {
    if (!editing) return;
    const label = editing === "details" ? pending.trim() : "";
    if (label && (labelRuleError(label) || draft.labels.includes(label))) return;
    void commit(editing, label ? { ...draft, labels: [...draft.labels, label] } : draft, evidence);
  }, [commit, draft, editing, evidence, pending]);
  /** A comment is its own write: it changes no field, lands in Comments and never checkpoints or moves the task. */
  const post = async () => {
    if (!comment.trim() || posting) return;
    setPosting(true);
    const ok = await postComment(p.task.id, base, comment);
    setPosting(false);
    if (!ok) return setToast("Comment not posted");
    setComment("");
    const fresh = await fetchRecord(p.task.id);
    if (fresh) p.onSaved?.(fresh, []);
    setToast("✓ Comment posted");
  };
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
  const { activity, machines, comments } = taskActivity(p.task, base.comments ?? []);
  /** A checkpoint's AC tag brings its criterion into view and flashes it, as the approved mockup does. */
  const jump = (event: MouseEvent<HTMLAnchorElement>, n: number) => {
    event.preventDefault();
    const row = event.currentTarget.closest(".modal")?.querySelector(`#ac${n}`);
    if (!row) return;
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    row.classList.add("flash");
    setTimeout(() => row.classList.remove("flash"), 1400);
  };
  const ev = (e: ActivityEvent) => (
    <div key={e.key} className="ev" data-kind={e.kind}>
      <span className="dot" />
      <div className="hd"><span className="who">{e.who}</span><span>{fmtAt(e.at)}</span>
        {e.ac !== undefined && <a className="tag" href={`#ac${e.ac}`} onClick={(event) => jump(event, e.ac!)}>AC #{e.ac}</a>}
        {e.kind === "system" && <span>event</span>}</div>
      <div className="bd"><Inline text={e.body} open={p.open} /></div>
      {e.detail && <details className="out"><summary>output</summary><pre>{e.detail}</pre></details>}
    </div>
  );
  const deps = dependencyRows(p.tasks, p.task);
  const offered = columnsOf(names, roles).filter((c) => c in p.task.moves).map((c) => ({
    to: c, text: names[c] ?? c, allowed: p.task.moves[c].allowed, reason: p.task.moves[c].reason ?? "",
  }));
  const startVisible = startLane(p.task, roles) && !p.claiming;
  const working = roles.working ? p.task.moves[roles.working] : undefined;
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
      setEvidence={(n, value) => setEvidence((all) => ({ ...all, [n]: value }))} open={p.open} />,`${items.filter((i) => i.checked).length}/${items.length}`);
  };
  const prose = (section: "plan" | "notes", name: string) => {
    const shown = section === "notes" ? taskBody(draft).notes : draft.plan;
    // An empty plan has no section to show: only an entry point to write one.
    if (section === "plan" && editing !== section && !shown.trim()) return canEdit ? <button className="addbtn" onClick={() => edit(section)}>+ Add plan</button> : null;
    return sec(section, name, editing === section
      ? <Txt {...fp(section)} value={draft[section]} label={name} long focus onChange={(value) => change(section, value)} />
      : shown.trim() ? <Md text={shown} open={p.open} /> : <span className="none">—</span>);
  };
  const row = (name: string, value: ReactNode, className?: string) => <tr key={name} className={className}><td>{name}</td><td>{value}</td></tr>;
  const tab = (on: boolean, text: string) => <button role="tab" aria-selected={preview === on} className={preview === on ? "on" : ""} onClick={() => setPreview(on)}>{text}</button>;

  return (
    <div id="kbm" onClick={(event) => onScrim(event.target, event.currentTarget) && p.close()}>
      <div className="modal tv" role="dialog" aria-label={`${p.task.id} ${base.title}`} aria-busy={!p.record && !p.readNote}>
        <div className="tvhead">
          <div className="tvmeta">
            <span className="tid">{p.task.id}</span>
            <button className={`copybtn${copied ? " ok" : ""}`} title={`Copy “${copyText(p.task, base.title)}”`} aria-label="Copy id and title" onClick={copy}>
              <span className="g">⧉</span>{copied ? "Copied" : "Copy"}
            </button>
            <LanePill lane={p.task.lane} role={roleOf(roles, p.task.lane)} name={p.lane} />
            {p.saving && <span className="k">saving</span>}
            {phone ? <span className="off" aria-disabled="true" title="Star Map is desktop-only">Open in Star Map ↗</span> : <a href="/" onClick={(e) => { e.preventDefault(); p.constellation(); }}>Open in Star Map ↗</a>}
            <div className="acts">
              {startVisible && <button className="startbtn" disabled={!startable(p.task, roles) || unavailable}
                title={startable(p.task, roles) ? undefined : working?.reason}
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
            {readDoc ? <DocReader link={readDoc} milestone={docs.milestone} back={() => setReading(null)} open={p.open} /> : <>
            {p.readNote}
            {writeRefusal && <div className="editrefusal"><b>Save refused.</b> {writeRefusal.reason}{writeRefusal.skill && <div>Required skill: <code>{writeRefusal.skill}</code></div>}</div>}
            {sec("description", "Description", editing === "description" ? <>
              <div className="tabs" role="tablist">{tab(false, "Write")}{tab(true, "Preview")}<span className="k">Markdown</span></div>
              {preview ? <Md text={draft.description} className="md prev" drawn={criteria.length > 0} open={p.open} /> : <Txt {...fp("description")} value={draft.description} label="Description" long focus onChange={(value) => change("description", value)} />}
            </> : <Md text={taskBody(draft).description} drawn={criteria.length > 0} open={p.open} />)}
            {p.record && checks("acceptanceCriteria", "Acceptance criteria")}
            {p.record && checks("definitionOfDone", "Definition of done")}
            {p.record && prose("plan", "Implementation plan")}
            {p.record && prose("notes", "Notes")}
            <section className="sec" id="activity">
              <div className="sh"><span className="t">Activity</span>{activity.length > 0 && <span className="n">{activity.length}</span>}</div>
              {activity.length > 0 && <div className="acts2">{activity.map(ev)}</div>}
              {machines.map((m) => (
                <details key={m.machine} className="mgroup">
                  <summary><span className="who">{m.machine}</span><span className="n">{m.steps.length}</span>
                    <span className="st">{m.state.replace(/_/g, " ")}</span><span>{fmtAt(m.at)}</span></summary>
                  <div className="acts2">{m.steps.map(ev)}</div>
                </details>
              ))}
              {activity.length === 0 && machines.length === 0 && <span className="none">No activity yet</span>}
            </section>
            <section className="sec" id="comments">
              <div className="sh"><span className="t">Comments</span>{comments.length > 0 && <span className="n">{comments.length}</span>}</div>
              {comments.length > 0 && <div className="acts2">{comments.map(ev)}</div>}
              {canEdit && (
                <div className="compose">
                  <textarea aria-label="Add a comment" placeholder="Add a comment" value={comment} onChange={(e) => setComment(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void post(); } }} />
                  <button disabled={!comment.trim() || posting} onClick={() => void post()}>Comment</button>
                </div>
              )}
            </section>
            </>}
          </div>
          <div className="tvcol tvrail">
            {p.refusal}
            {p.startNote}
            <RailSection name="Status">
              <div className="row"><LanePill lane={p.task.lane} role={roleOf(roles, p.task.lane)} name={p.lane} small />{p.task.entered > 0 && <span className="k">{`for ${ago(p.now - p.task.entered)}`}</span>}</div>
              {p.stack && <table className="props"><tbody><tr className="ro"><td>{p.task.lane === roles.done ? "done chain" : "waiting stack"}</td><td className="stacklist">{p.stack}</td></tr></tbody></table>}
            </RailSection>
            {p.task.labels.some((l) => l.startsWith(TRIAL)) && <RailSection name="Rating"><RatingControl key={p.task.id} task={p.task.id} rating={p.task.rating} now={p.now} trial={p.task.labels.find((l) => l.startsWith(TRIAL)) ?? ""} drew={p.task.profile ?? ""} /></RailSection>}
            <RailSection name="Session"><SessionRows session={sessionOf(p.task, p.record, p.now, startLane(p.task, roles))} assignee={p.task.assignee} worked={p.task.lane === roles.working} startLane={startLane(p.task, roles)} /></RailSection>
            {criteria.length > 0 && <RailSection name="Start Criteria" count={`${metCount(criteria)}/${criteria.length} met`}><StartCriteria criteria={criteria} now={p.now} /></RailSection>}
            {!!p.task.runs?.length && (
              <RailSection name="Runs" count={p.task.runs.length}>
                {p.task.runs.map((r) => <div key={`${r.url} ${r.startedAt}`} className="pull"><a href={r.url} target="_blank" rel="noopener">{runStart(r.startedAt)} ↗</a><span className="k">{r.status}</span></div>)}
              </RailSection>
            )}
            <RailSection name="Pull requests" count={p.task.prs.length}><PullRows task={p.task} /></RailSection>
            <RailSection name="Dependencies" count={deps.dependsOn.length + deps.holds.length + deps.more}>
              <div className="deps">
                <div className="lb">Depends on</div>
                {deps.dependsOn.length ? <Box><DepRows rows={deps.dependsOn} names={names} roles={roles} open={p.open} /></Box> : <span className="none">—</span>}
                {deps.holds.length > 0 && <>
                  <div className="lb">Holds</div>
                  <Box><DepRows rows={deps.holds} names={names} roles={roles} open={p.open} /></Box>
                  {deps.more > 0 && <div className="k">+{deps.more} more</div>}
                </>}
              </div>
            </RailSection>
            {docs.links.length > 0 && <RailSection name="Docs" count={docs.links.length}>
              <DocRows links={docs.links} reading={readDoc?.id ?? null} open={(doc) => setReading({ task: p.task.id, doc })} />
            </RailSection>}
            {sec("details", "Details", (() => {
              const live = editing === "details";
              const { chips, ...fields } = detailFields(draft.labels);
              const labelFp = { ...fp("labels", "details"), bad: false };
              const areas = [...new Set([...p.tasks.map((t) => detailFields(t.labels).area), fields.area])].filter(Boolean).sort();
              const field = (name: LabelField, options: string[]) => (
                <Select {...labelFp} label={name[0].toUpperCase() + name.slice(1)} value={fields[name]}
                  options={[["", "—"], ...options.map((v): [string, string] => [v, v])]} onChange={(value) => change("labels", setDetailField(draft.labels, name, value))} />
              );
              const note = typedError || labelRefusal;
              return (
                <table className="props"><tbody>
                  {row("kind", live ? field("kind", LABEL_FIELDS.kind) : fields.kind || "—")}
                  {row("size", live ? field("size", LABEL_FIELDS.size) : fields.size ? <span className="sz">{fields.size}</span> : "—")}
                  {row("area", live ? field("area", areas) : fields.area || "—")}
                  {(live || fields.mode) && row("mode", live ? field("mode", LABEL_FIELDS.mode) : fields.mode)}
                  {row("priority", live ? <Select {...fp("priority", "details")} label="Priority" value={priorityValue(draft.priority)} options={[["", "—"], ...PRIORITIES.map((v): [string, string] => [v, v])]} onChange={(value) => change("priority", value)} /> : priorityValue(draft.priority) || "—")}
                  {row("profile", live ? <Select {...fp("profile", "details")} label="Profile" value={draft.profile} options={[["", "unassigned"], ...(draft.profile && !p.profiles.includes(draft.profile) ? [...p.profiles, draft.profile] : p.profiles).map((v): [string, string] => [v, v])]} onChange={(value) => change("profile", value)} /> : draft.profile || "—")}
                  {!live && draft.type && row("type", draft.type)}
                  {row("labels", live ? <>
                    <div className={fieldClass("fv chips", true, Boolean(note))}>
                      {chips.map((v) => <Chip key={v} value={v} remove={(value) => change("labels", draft.labels.filter((label) => label !== value))} />)}
                      <input className="chipinput" placeholder="add label" aria-label="Add label" value={pending}
                        onChange={(e) => { setPending(e.currentTarget.value); setLabelRefusal(""); }}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) { e.preventDefault(); addLabel(); } }} />
                    </div>
                    <div className={`rule${note ? " err" : ""}`} role="status">{note || LABEL_RULE}</div>
                  </> : <ChipList values={chips} />, "sep")}
                  {row("milestone", live ? <Select {...fp("milestone", "details")} label="Milestone" value={draft.milestone} options={[["", "—"], ...p.milestones.map((v): [string, string] => [v, v])]} onChange={(value) => change("milestone", value)} /> : draft.milestone || "—")}
                  {!live && row("created", <span className="k">{p.task.created ? `${ago(p.now - p.task.created)} ago` : "—"}</span>)}
                </tbody></table>
              );
            })(), undefined, true)}
          </div>
        </div>
        {toast && <div className="toast" role="status">{toast}</div>}
      </div>
    </div>
  );
}
