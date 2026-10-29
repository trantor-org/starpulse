// The operator's answer to the question a task in Needs attention waits on, written on the card.
import { useState } from "react";
import { postAnswer } from "./answer";

export function AnswerForm({ task }: { task: string }) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const [recorded, setRecorded] = useState(false);

  const send = async () => {
    setBusy(true);
    const result = await postAnswer(task, draft.trim());
    setBusy(false);
    if ("refused" in result) { setRefused(result.refused); setRecorded(false); return; }
    setRefused(null);
    setRecorded(true);
    setDraft("");
  };

  return (
    <div className="compose">
      <textarea aria-label="Answer the question" placeholder="Answer the question this task waits on" value={draft}
        onChange={(e) => { setDraft(e.target.value); setRecorded(false); }}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && draft.trim() && !busy) { e.preventDefault(); void send(); } }} />
      <button disabled={!draft.trim() || busy} onClick={() => void send()}>Answer</button>
      {recorded && <div className="ratemeta">Answered as operator</div>}
      {refused && <div className="editrefusal" role="alert">Answer not saved: {refused}</div>}
    </div>
  );
}
