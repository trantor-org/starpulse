// The archive confirm: a reason, a warning for work that outlives the task, and the writer's refusal.
import { useEffect, useState } from "react";
import { archiveKey, archiveWarnings, postArchive } from "./archive";
import type { KanbanTask } from "./kanban";

export interface ArchiveConfirmProps {
  task: KanbanTask;
  lane: string;
  reason: string;
  busy: boolean;
  refused: string | null;
  onReason: (reason: string) => void;
  cancel: () => void;
  confirm: () => void;
}

export function ArchiveConfirm({ task, lane, reason, busy, refused, onReason, cancel, confirm }: ArchiveConfirmProps) {
  const { pull, session } = archiveWarnings(task);
  return (
    <div id="efa" onClick={(event) => event.target === event.currentTarget && !busy && cancel()}>
      <div className="box" role="alertdialog" aria-label={`Archive ${task.id}`}>
        <h3>Archive {task.id}?</h3>
        <div className="k">{task.title} · {lane}</div>
        <div>It leaves the board for the archive. Its file, comments and history are kept; nothing else about the task changes.</div>
        {pull && (
          <div className="warn">⚠<span>Pull request <a href={pull.url} target="_blank" rel="noopener">#{pull.number}</a> is open (checks {pull.checks}). Archiving does not close it.
            <span className="k3">Close or merge it on GitHub if it should not land.</span></span></div>
        )}
        {session && (
          <div className="warn">⚠<span>An agent session is working this task ({session.machine} · {session.state}). Archiving does not stop it.
            <span className="k3">The session's next board write will be refused once the task is archived.</span></span></div>
        )}
        <label><span>Reason <i>· optional, saved as a task comment</i></span>
          <textarea autoFocus value={reason} aria-label="Reason" disabled={busy}
            placeholder="e.g. superseded by the m-80 cohort; test task created by a leaked fixture" onChange={(e) => onReason(e.currentTarget.value)} />
        </label>
        {refused && <div className="refused" role="alert">Not archived: {refused}</div>}
        <div className="row">
          <span className="hint">Esc cancels · Ctrl+Enter archives</span>
          <span className="sp" />
          <button onClick={cancel} disabled={busy}>Cancel</button>
          <button className="danger" disabled={busy} onClick={confirm}>{busy ? "Archiving…" : refused ? "Try again" : `Archive ${task.id}`}</button>
        </div>
      </div>
    </div>
  );
}

/** The confirm with its own state: it posts the archive, closes on success and, on a refusal, stays open with the reason. */
export function ArchiveDialog({ task, lane, close, archived }: { task: KanbanTask; lane: string; close: () => void; archived: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setRefused(null);
    const result = await postArchive(task.id, reason.trim());
    setBusy(false);
    if (result.ok) archived(reason.trim());
    else setRefused(result.reason);
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const action = archiveKey(event.key, event.ctrlKey, event.metaKey, busy);
      if (!action) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (action === "cancel") close();
      else void confirm();
    };
    addEventListener("keydown", onKey, true);
    return () => removeEventListener("keydown", onKey, true);
  });
  return <ArchiveConfirm task={task} lane={lane} reason={reason} busy={busy} refused={refused} onReason={setReason} cancel={close} confirm={() => void confirm()} />;
}
