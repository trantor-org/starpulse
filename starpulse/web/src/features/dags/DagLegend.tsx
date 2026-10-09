// The DAGs view's legend lines. Its own module, so the right rail can draw them without loading the view.
import type { CSSProperties } from "react";
import { Orb, StepStar } from "./DagParts";

const key = (c: string): CSSProperties => ({ color: c });

/** The legend panel's lines for this view. */
export function DagLegend() {
  return (
    <>
      <span><Orb phase="running" />running</span><span><Orb phase="ok" />healthy</span><br />
      <span><Orb phase="failed" />last run failed</span><span><Orb phase="idle" />never run</span><br />
      <span><svg width="34" height="12" aria-hidden="true"><path d="M9 6H13M21 6H25" className="e" /><StepStar x={5} y={6} r={4} status="succeeded" /><StepStar x={17} y={6} r={4} status="running" /><StepStar x={29} y={6} r={4} status="not_started" /></svg> steps</span>
      <span><svg width="14" height="14" aria-hidden="true"><StepStar x={7} y={7} r={4} status="succeeded" /><circle cx="7" cy="7" r="6.5" className="ring" /></svg> agent step</span><br />
      <span><span style={key("var(--agent)")}>⇢</span> Board tie</span><span><span style={key("var(--ok)")}>▶</span> run-safe</span>
    </>
  );
}
