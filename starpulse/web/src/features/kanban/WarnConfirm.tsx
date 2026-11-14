// The warn-and-confirm box: an operator move that breaks lane rules lists each one, and writes only on Confirm.
import { useEffect, useRef, useState } from "react";
import { archiveKey } from "./archive";
import { codeParts } from "./move";
import type { RuleBreak } from "../../api";
import type { KanbanTask } from "./kanbanModel";

export interface WarnConfirmProps {
  task: KanbanTask;
  from: string;
  to: string;
  warnings: RuleBreak[];
  busy: boolean;
  refused: string | null;
  cancel: () => void;
  confirm: () => void;
}

export function WarnConfirm({ task, from, to, warnings, busy, refused, cancel, confirm }: WarnConfirmProps) {
  const rules = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const count = warnings.length;
  const [opener] = useState(() => (typeof document === "undefined" ? null : document.activeElement));
  useEffect(() => () => {
    if (opener instanceof HTMLElement && opener !== document.body && opener.isConnected) opener.focus();
  }, [opener]);
  useEffect(() => {
    const list = rules.current;
    if (!list) return;
    const measure = () => setOverflows(list.scrollHeight > list.clientHeight);
    measure();
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watch?.observe(list);
    return () => watch?.disconnect();
  }, [warnings]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const action = archiveKey(event.key, event.ctrlKey, event.metaKey, busy);
      if (!action || (action === "confirm" && refused)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      if (action === "cancel") cancel();
      else confirm();
    };
    addEventListener("keydown", onKey, true);
    return () => removeEventListener("keydown", onKey, true);
  });
  return (
    <div id="efa" onClick={(event) => event.target === event.currentTarget && !busy && cancel()}>
      <div className="box" role="alertdialog" aria-label={`Move ${task.id} to ${to}`}>
        <h3>Move {task.id} to {to}?</h3>
        <div className="k">{task.title} · {from} → {to}</div>
        <div className="lead">This move breaks {count} {count === 1 ? "rule" : "rules"} of the {to} lane. An agent making it would be refused.</div>
        <div className="rules" role="list" aria-label="Broken rules" ref={rules} tabIndex={overflows ? 0 : undefined}>
          {warnings.map((rule) => (
            <div className="warn" role="listitem" key={rule.reason}>
              <span className="g" aria-hidden="true">⚠</span>
              <div>
                {codeParts(rule.reason).map((part, i) => (part.code ? <code key={i}>{part.text}</code> : part.text))}
                {rule.skill && <span className="k3">Satisfied by <span className="skill">{rule.skill}</span></span>}
              </div>
            </div>
          ))}
        </div>
        {refused && <div className="refused" role="alert">Not moved: {refused.replace(/\.$/, "")}. Cancel, then move it again to see the current rules.</div>}
        <div className="row">
          <span className="hint">Esc cancels · Ctrl+Enter confirms</span>
          <span className="sp" />
          <button autoFocus onClick={cancel} disabled={busy}>Cancel</button>
          <button className="danger" disabled={busy || refused !== null} onClick={confirm}>{busy ? "Moving…" : "Confirm"}</button>
        </div>
      </div>
    </div>
  );
}
