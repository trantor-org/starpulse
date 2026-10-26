// The Rating section's body in the task view, drawn on a deviated sample (a `trial-<kind>-<size>` task): what was sampled, then Pass and Fail toggle the task's verdict, Fail asks for a one-line reason.
import { useState, type KeyboardEvent } from "react";
import { PAGE_ACTOR } from "../../api/apiFetch";
import type { Rating } from "../../api";
import { ago, fmtAt } from "../../shared/clock";
import { postRating, ratingHistory, ratingMeta, REASON_MAX, verdictOf, type Verdict } from "./rating";

/** A write's answer stands in for the snapshot until the snapshot's own rating moves on from the one the write began from. */
interface Mine { base: Rating | undefined; rating: Rating }
const sameRating = (a: Rating | undefined, b: Rating | undefined) => a?.changes === b?.changes && a?.at === b?.at;

/** `trial-decide-5` names the cell a step-down trial samples: its kind and size. */
const trialCell = (trial: string) => {
  const cell = /^trial-(.+)-(\d+)$/.exec(trial);
  return cell ? `${cell[1]} work at size ${cell[2]}` : "this kind of work";
};

export function RatingControl({ task, rating, now, trial, drew }: { task: string; rating: Rating | undefined; now: number; trial: string; drew: string }) {
  const [mine, setMine] = useState<Mine | null>(null);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const shown = mine && sameRating(mine.base, rating) ? mine.rating : rating;
  const verdict = verdictOf(shown);

  const write = async (next: Verdict, reason = ""): Promise<boolean> => {
    setBusy(true);
    setRefused(false);
    const rated = await postRating(task, next, reason);
    setBusy(false);
    if (!rated) { setRefused(true); return false; }
    setMine({ base: rating, rating: { verdict: rated.verdict, reason: rated.reason, at: now, actor: PAGE_ACTOR, changes: rated.changes } });
    return true;
  };
  const toggle = async (next: "pass" | "fail") => {
    const cleared = verdict === next;
    setDraft(null);
    if (await write(cleared ? "cleared" : next) && next === "fail" && !cleared) setDraft("");
  };
  const saveReason = async () => {
    if (draft === null) return;
    if (draft.trim() === (shown?.reason ?? "") || !draft.trim()) { setDraft(null); return; }
    if (await write("fail", draft.trim())) setDraft(null);
  };
  /** Esc skips the reason and nothing more: the modal's own Esc listener sees a handled key and stays open. */
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") { event.preventDefault(); void saveReason(); }
    else if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setDraft(null); }
  };
  const verdictButton = (v: "pass" | "fail") =>
    <button type="button" className="ratebtn" data-verdict={v} aria-pressed={verdict === v} disabled={busy} onClick={() => void toggle(v)}>{v === "pass" ? "Pass" : "Fail"}</button>;

  return (
    <>
      <div className="why">Deviated sample: this run drew a <b>lower</b> tier than the matrix assigns, to test whether {trialCell(trial)} can run there.</div>
      {drew && <dl className="who2 dev"><dt>Drew</dt><dd>{drew} <span className="tier">↓ lower</span></dd></dl>}
      <div className="why">Did the work hold up?</div>
      <div className="rate">{verdictButton("pass")}{verdictButton("fail")}</div>
      {verdict === "fail" && shown && (
        <div className="ratewhy">
          {draft !== null ? (
            <>
              <input className="fv live" autoFocus maxLength={REASON_MAX} aria-label="Reason" placeholder="Why, in one line (optional)" value={draft} disabled={busy} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKeyDown} />
              <span className={`count${draft.length >= REASON_MAX ? " full" : ""}`}>{draft.length}/{REASON_MAX}</span>
              <span className="k">Enter saves · Esc skips</span>
            </>
          ) : (
            <>
              {shown.reason && <span>{shown.reason}</span>}
              <button type="button" onClick={() => setDraft(shown.reason)}>{shown.reason ? "Edit" : "Add a reason"}</button>
            </>
          )}
        </div>
      )}
      {busy ? <div className="ratemeta">saving</div> : verdict && shown && <div className="ratemeta" title={ratingHistory(shown, fmtAt(shown.at))}>{ratingMeta(shown, verdict, shown.at >= now ? "now" : `${ago(now - shown.at)} ago`)}</div>}
      {refused && <div className="editrefusal" role="alert">Rating not saved.</div>}
    </>
  );
}
