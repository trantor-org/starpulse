import { CROSS } from "../features/level/ledgerRows";
import { DAG_COLOR } from "./draw";

/** The Ledger's colours by run state: an overdue cue is drawn as a failure, and another repository's unapplied merge as waiting. */
export const LEDGER_PALETTE: Record<string, string> = { ...DAG_COLOR, waiting: CROSS, overdue: DAG_COLOR.failed };
