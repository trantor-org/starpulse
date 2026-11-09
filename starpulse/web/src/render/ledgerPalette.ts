import { CROSS } from "../features/level/ledgerRows";
import { DAG_COLOR } from "./draw";
import { onTheme } from "./palette";

/** The Ledger's colours by run state: an overdue cue is drawn as a failure, and another repository's unapplied merge as waiting. Repainted with the theme. */
export const LEDGER_PALETTE: Record<string, string> = {};
onTheme(() => Object.assign(LEDGER_PALETTE, DAG_COLOR, { waiting: CROSS, overdue: DAG_COLOR.failed }));
