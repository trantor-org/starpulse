// The fidelity ledger of the In Progress drill-in: one row per live note of the owner's design record (doc-986), each with where the build
// answers it. A note a later one reverses stays listed as superseded, so no row is lost. "render" marks what only the live render can show.
export interface Row {
  n: number;
  note: string;
  /** What shows the note applied: a test file, or "render" when the operator's live approval is the evidence. */
  by: string;
  supersededBy?: number;
}

const ROWS: Omit<Row, "n">[] = [
  { note: "Delayed disclosure: labels by default, hover shows details and backtraces, click shows data.", by: "SunsDrillIn.test.tsx" },
  { note: "No legends.", by: "SunsDrillIn.test.tsx" },
  { note: "Text must not intersect flow lines.", by: "sunsBoard.test.ts" },
  { note: "Clean, minimal, intuitive.", by: "render" },
  { note: "Exits are lines, not states.", by: "sunsBoard.test.ts" },
  { note: "One row per machine, with round pills.", by: "sunsBoard.test.ts" },
  { note: "Flow lines stream dashed as in StarPulse and draw into the rows.", by: "render" },
  { note: "Flow lines are rounded.", by: "render" },
  { note: "Needs Attention and Done exits are flat curves that never cross.", by: "sunsBoard.test.ts" },
  { note: "A routing lane beside the pills feeds every row; no grey rail.", by: "sunsBoard.test.ts" },
  { note: "The routing lane stays visible.", by: "sunsBoard.test.ts" },
  { note: "The left panel is the task picker, titled Tasks.", by: "SunsDrillIn.test.tsx" },
  { note: "True per-task replay of the last 24 hours.", by: "sunsReplay.test.ts" },
  { note: "No green line left of the lens rows.", by: "render" },
  { note: "States are suns, not hexagons.", by: "sunsDraw.test.ts" },
  { note: "No grey line from the old round marker.", by: "render" },
  { note: "No yellow for progress; the existing task animation.", by: "sunsDraw.test.ts" },
  { note: "No expanded view and no expand indicators.", by: "sunsBoard.test.ts" },
  { note: "Lens rows are drawn from each lens's own machine.", by: "sunsDrill.test.ts" },
  { note: "Nothing moves on load; labels and pills move on a real transition.", by: "sunsDraw.test.ts" },
  { note: "Every stem runs along its hairline into the routing lane.", by: "sunsBoard.test.ts" },
  { note: "No separator lines between lens rows.", by: "sunsBoard.test.ts", supersededBy: 24 },
  { note: "Phase and lens routing lines lie on top of each other, with the same arc.", by: "sunsBoard.test.ts" },
  { note: "Keep the separator between phase and lens machines; lines between groups only.", by: "sunsBoard.test.ts" },
  { note: "Entry and exit lines stem from the pane's left and right edges.", by: "sunsBoard.test.ts" },
  { note: "Exit labels sit left of the arrowheads without touching them.", by: "sunsBoard.test.ts" },
  { note: "Spread out the header; use the empty space beside the lens rows.", by: "render" },
  { note: "Exit hover says what each exit means.", by: "sunsHover.test.ts" },
  { note: "The arrival ring is the task's own colour, never amber.", by: "sunsDraw.test.ts" },
];

export const LEDGER: Row[] = ROWS.map((r, i) => ({ n: i + 1, ...r }));
