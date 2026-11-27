// The Kanban toolbar's New task: a button that opens a form, laid out like the task view, for every field a new task takes;
// the card lands in the board's starting lane.
import { useState } from "react";
import { EMPTY_DRAFT, createOutcome, newTaskKey, postCreate, refusedField, type NewTaskDraft } from "./newTaskModel";
import { LEVELS, PRIORITIES } from "./taskViewModel";

type Field = Exclude<keyof NewTaskDraft, "acceptanceCriteria">;

type Text = "outcome" | "why" | "currentState" | "scope" | "outOfScope" | "stopConditions" | "rollback";
const BRIEF_TEXT: [Text, string, number, string][] = [
  ["outcome", "Outcome", 2, "One line, at most 200 characters"],
  ["why", "Why", 3, "One line, at most 400 characters"],
  ["currentState", "Current state", 3, "One line, at most 400 characters"],
  ["scope", "Scope", 3, "One item per line"],
  ["outOfScope", "Out of scope", 3, "One item per line"],
  ["stopConditions", "Stop conditions", 3, "One item per line"],
  ["rollback", "Rollback", 2, "Required when undo is 2 or more"],
];
const AXES = ["reach", "data", "undo", "detect"] as const;
const ONE_LINE: Text[] = ["outcome", "why", "currentState", "rollback"];

const Refusal = ({ id, text }: { id: string; text: string | null }) => <div id={id} className="editrefusal" role="alert">{text}</div>;

export interface NewTaskFormProps {
  draft: NewTaskDraft;
  busy: boolean;
  refused: string | null;
  /** The name of the lane the task lands in. */
  lane: string;
  assignees: string[];
  milestones: string[];
  change: (draft: NewTaskDraft) => void;
  cancel: () => void;
  submit: () => void;
}

export function NewTaskForm({ draft, busy, refused, lane, assignees, milestones, change, cancel, submit }: NewTaskFormProps) {
  const set = (field: Field) => (e: { currentTarget: { value: string } }) => change({ ...draft, [field]: e.currentTarget.value });
  const criteria = draft.acceptanceCriteria.length ? draft.acceptanceCriteria : [""];
  const setCriteria = (items: string[]) => change({ ...draft, acceptanceCriteria: items });
  const bad = refusedField(refused);
  const ready = !busy && !!draft.title.trim();
  return (
    <div id="kbm" onClick={(e) => e.target === e.currentTarget && cancel()}>
      <div className="modal tv editing newtaskform" role="dialog" aria-label="New task" onKeyDown={(e) => {
        const action = newTaskKey(e.key, e.ctrlKey || e.metaKey, busy);
        if (!action) return;
        e.preventDefault();
        if (action === "cancel") cancel();
        else if (ready) submit();
      }}>
        <button className="x" onClick={cancel} aria-label="Close">✕</button>
        <div className="tvhead">
          <div className="ttl">
            <input autoFocus className="fv title" value={draft.title} aria-label="Title" placeholder="Title of the new task" maxLength={300} disabled={busy} onChange={set("title")} />
            <div className="k">New task · Lands in {lane}</div>
          </div>
          <div className="acts">
            <button className="cancelbtn" disabled={busy} onClick={cancel}>Cancel <kbd>Esc</kbd></button>
            <button className="savebtn" disabled={!ready} onClick={submit}>{busy ? "Creating…" : "Create"} <kbd>Ctrl+Enter</kbd></button>
          </div>
        </div>
        <div className="tvbody">
          {refused && <div className="editrefusal" role="alert"><b>Not created.</b> {refused}</div>}
          <table><tbody>
            <tr><td>assignee</td><td><input className="fv" list="nt-assignees" value={draft.assignee} aria-label="Assignee" placeholder="unassigned" disabled={busy} onChange={set("assignee")} /></td></tr>
            <tr><td>priority</td><td>
              <select className="fv" value={draft.priority} aria-label="Priority" disabled={busy} onChange={set("priority")}>
                {[["", "—"], ...PRIORITIES.map((v) => [v, v])].map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </td></tr>
            <tr><td>impact</td><td>
              <select className="fv" value={draft.impact} aria-label="Impact" disabled={busy} onChange={set("impact")}>
                {[["", "—"], ...LEVELS.map((v) => [v, v])].map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </td></tr>
            <tr><td>urgency</td><td>
              <select className="fv" value={draft.urgency} aria-label="Urgency" disabled={busy} onChange={set("urgency")}>
                {[["", "—"], ...LEVELS.map((v) => [v, v])].map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </td></tr>
            <tr><td>labels</td><td><input className="fv" value={draft.labels} aria-label="Labels" placeholder="comma-separated" disabled={busy} onChange={set("labels")} /></td></tr>
            <tr><td>milestone</td><td><input className="fv" list="nt-milestones" value={draft.milestone} aria-label="Milestone" placeholder="—" disabled={busy} onChange={set("milestone")} /></td></tr>
            <tr><td>depends on</td><td><input className="fv" value={draft.dependencies} aria-label="Dependencies" placeholder="task ids, comma-separated" disabled={busy} onChange={set("dependencies")} /></td></tr>
          </tbody></table>
          <datalist id="nt-assignees">{assignees.map((v) => <option key={v} value={v} />)}</datalist>
          <datalist id="nt-milestones">{milestones.map((v) => <option key={v} value={v} />)}</datalist>
          {BRIEF_TEXT.map(([field, label, rows, hint]) => (
            <section className="sec" key={field}>
              <div className="sh"><span className="t">{label}</span></div>
              <textarea className={ONE_LINE.includes(field) ? "fv" : "fv long"} rows={rows} value={draft[field]} aria-label={label} aria-invalid={bad === field} aria-describedby={bad === field ? `nt-${field}-err` : undefined} placeholder={hint} disabled={busy} onChange={set(field)} />
              {bad === field && <Refusal id={`nt-${field}-err`} text={refused} />}
            </section>
          ))}
          <section className="sec">
            <div className="sh"><span className="t">Blast radius</span></div>
            <table><tbody>
              {AXES.map((field) => (
                <tr key={field}><td>{field}</td><td>
                  <select className="fv" value={draft[field]} aria-label={`Blast radius ${field}`} aria-invalid={bad === field} aria-describedby={bad === field ? `nt-${field}-err` : undefined} disabled={busy} onChange={set(field)}>
                    {["", "0", "1", "2", "3"].map((v) => <option key={v} value={v}>{v || "—"}</option>)}
                  </select>
                  {bad === field && <Refusal id={`nt-${field}-err`} text={refused} />}
                </td></tr>
              ))}
            </tbody></table>
            <textarea className="fv" rows={1} value={draft.blastNote} aria-label="Blast radius note" aria-invalid={bad === "blastNote"} aria-describedby={bad === "blastNote" ? "nt-blastNote-err" : undefined} placeholder="One sentence on the worst axis" disabled={busy} onChange={set("blastNote")} />
            {bad === "blastNote" && <Refusal id="nt-blastNote-err" text={refused} />}
          </section>
          <section className="sec">
            <div className="sh"><span className="t">Acceptance criteria</span></div>
            <div className="list">
              {criteria.map((text, at) => (
                <div key={at} className="item">
                  <span className="n">#{at + 1}</span>
                  <input type="text" className="fv" value={text} aria-label={`Acceptance criterion #${at + 1}`} disabled={busy}
                    onChange={(e) => setCriteria(criteria.map((old, i) => i === at ? e.currentTarget.value : old))} />
                  <button className="remove" aria-label={`Remove acceptance criterion #${at + 1}`} disabled={busy}
                    onClick={() => setCriteria(criteria.filter((_, i) => i !== at))}>−</button>
                </div>
              ))}
              <button className="add" disabled={busy} onClick={() => setCriteria([...criteria, ""])}>+ Add criterion</button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

/** New task with its own state, drawn only when the snapshot says the board creates; closing keeps the draft until it is created. */
export function NewTaskAction({ lane, assignees, milestones, created }: {
  lane: string; assignees: string[]; milestones: string[]; created: (task: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<NewTaskDraft>(EMPTY_DRAFT);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const submit = async () => {
    if (busy || !draft.title.trim()) return;
    setBusy(true);
    setRefused(null);
    const next = createOutcome(draft, await postCreate(draft));
    setBusy(false);
    setDraft(next.draft);
    setRefused(next.refused);
    if (next.created) { setOpen(false); created(next.created); }
  };
  return <>
    <button className="tbtn" onClick={() => setOpen(true)}>+ New task</button>
    {open && <NewTaskForm draft={draft} busy={busy} refused={refused} lane={lane} assignees={assignees} milestones={milestones}
      change={setDraft} cancel={() => setOpen(false)} submit={() => void submit()} />}
  </>;
}
