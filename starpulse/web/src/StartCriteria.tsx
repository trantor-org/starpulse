// The task view's Start Criteria: one card per criterion the description declares, with the result the board gave it.
import { criterionDetail, type StartCriterion } from "./taskView";

const MARKS: Record<string, string> = { met: "✓ met", unmet: "○ unmet", error: "error" };

/** A criterion's card: a met or unmet mark, its kind and id, its expression, then the evaluator's error or `threshold · last value · checked <age>`. */
export function StartCriteria({ criteria, now }: { criteria: StartCriterion[]; now: number }) {
  return (
    <div className="crit">
      {criteria.map((c) => {
        const state = c.status in MARKS ? c.status : "pending";
        const detail = criterionDetail(c, now);
        return (
          <div key={c.id} className={`c ${state}`}>
            <div className="top">
              {MARKS[state] && <span className="st">{MARKS[state]}</span>}
              <span className="kind">{c.kind}</span><code className="cid">{c.id}</code>
            </div>
            <code className="expr" title={c.expr}>{c.expr}</code>
            {state === "error" && <div className="err" title={c.error ?? undefined}>{c.error || "the evaluator gave no reason"}</div>}
            {state === "pending" && <div className="k">not evaluated</div>}
            {detail && <div className="k">{detail}</div>}
          </div>
        );
      })}
    </div>
  );
}
