// What the Board's status dot and the note beside it say of the stream: the stream names what it is doing (`Link`), this words it.
import type { Link } from "../api/stream";
import type { HudState } from "./hud";

/** The note on a live dot once the server names a page build other than the one loaded: the page reloads when nobody is using it. */
export const UPDATING = "updating when idle";

/**
 * The dot and the note for a connection state. `at` is the clock time of the last data the page drew (null before the first), which a
 * note that replaces the stats line keeps visible: the Board is as of then. A live dot keeps `updating` while a reload is waiting.
 */
export function linkHud(link: Link, at: string | null, updating: boolean): Pick<HudState, "live" | "note"> {
  if (link === "live") return { live: "on", note: updating ? UPDATING : "" };
  const note = at ? `${link} · ${at} MST` : link;
  return { live: link === "offline" ? "off" : "wait", note };
}
