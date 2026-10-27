// The Board and machine-ledger canvases' colors beyond palette.ts: shades of the agent violet and the DAG amber that no single role names.
// Each is a role or a mix of two roles read from the :root tokens (token, mix), repainted when `sp:theme` fires like the palette's own
// exports, so a draw call that names one gets the theme's current color.
import { mix, onTheme, token } from "./palette";

/** A lifecycle machine's ring, track and flow-line end: the agent violet turned a little toward fail. */
export let MACHINE_RING = "";
/** A lifecycle machine's name, and the pale core of a sun. */
export let NAME_INK = "", CORE = "";
/** The stem that joins a machine's tasks, and the fuchsia disc at its foot: the violet turned further toward fail. */
export let STEM = "";
/** A DAG's mark on a ledger (its cue, badge and count), and the text on a badge. */
export let DAG_INK = "", DAG_HI = "";

onTheme(() => {
  MACHINE_RING = mix("agent", "fail", 0.15);
  NAME_INK = mix("agent-text", "agent-hi", 0.4);
  CORE = token("agent-hi");
  STEM = mix("agent", "fail", 0.35);
  [DAG_INK, DAG_HI] = [token("run-text"), token("run-hi")];
});
