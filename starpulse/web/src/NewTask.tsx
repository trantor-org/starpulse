// The Kanban toolbar's New task: a button that opens an inline title field; the card lands in the board's first column.
import { useState } from "react";
import { createOutcome, newTaskKey, postCreate } from "./newTask";
import type { Capabilities } from "./types";

export interface NewTaskProps {
  open: boolean;
  title: string;
  busy: boolean;
  refused: string | null;
  onOpen: () => void;
  onTitle: (title: string) => void;
  cancel: () => void;
  submit: () => void;
}

export function NewTask({ open, title, busy, refused, onOpen, onTitle, cancel, submit }: NewTaskProps) {
  if (!open) return <button className="tbtn" onClick={onOpen}>+ New task</button>;
  return (
    <span className="newtask">
      <input autoFocus value={title} aria-label="New task title" placeholder="Title of the new task" disabled={busy} maxLength={200}
        onChange={(e) => onTitle(e.currentTarget.value)} onKeyDown={(e) => {
          const action = newTaskKey(e.key, busy);
          if (!action) return;
          e.preventDefault();
          if (action === "cancel") cancel();
          else if (title.trim()) submit();
        }} />
      <button className="tbtn go" disabled={busy || !title.trim()} onClick={submit}>{busy ? "Adding…" : "Add"}</button>
      <button className="tbtn" disabled={busy} onClick={cancel}>Cancel</button>
      {refused && <span className="refused" role="alert">Not created: {refused}</span>}
    </span>
  );
}

/** New task with its own state, drawn only when the snapshot says the board creates; `created` is told the new task's id. */
export function NewTaskAction({ capabilities, created }: { capabilities?: Capabilities; created: (task: string) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  if (!capabilities?.create) return null;
  const close = () => { setOpen(false); setTitle(""); setRefused(null); };
  const submit = async () => {
    if (busy || !title.trim()) return;
    setBusy(true);
    setRefused(null);
    const next = createOutcome(title.trim(), await postCreate(title.trim()));
    setBusy(false);
    setTitle(next.title);
    setRefused(next.refused);
    if (next.created) { setOpen(false); created(next.created); }
  };
  return <NewTask open={open} title={title} busy={busy} refused={refused} onOpen={() => setOpen(true)} onTitle={setTitle} cancel={close} submit={() => void submit()} />;
}
