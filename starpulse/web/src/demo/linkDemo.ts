// The connection's states, played on the demo page so the Board's status dot and its note can be seen with no server to restart. The page
// address names one: `?link=restart`, `update` or `drop` plays it from live; `restarting`, `retrying`, `offline` or `updating` holds it.
import type { StreamHandlers } from "../api/stream";

const DRAWN_MS = 300;
const BEFORE_MS = 2000;
const OUTAGE_MS = 6000;
const HOLDS = new Set(["restarting", "retrying", "offline"]);

/** Plays the scenario `name` (null plays nothing) through `handlers`; `lostMs` is the page's wait before it calls the connection lost. The function returned stops it. */
export function playLink(handlers: Pick<StreamHandlers, "link" | "build">, name: string | null, lostMs: number): () => void {
  const timers: ReturnType<typeof setTimeout>[] = [];
  const at = (ms: number, fn: () => void) => void timers.push(setTimeout(fn, ms));
  const link: NonNullable<StreamHandlers["link"]> = (state) => handlers.link?.(state);
  const build = () => handlers.build?.("demo-next");

  // a held state comes once the page has drawn the Board, which its note's time is read from
  if (name && HOLDS.has(name)) at(DRAWN_MS, () => link(name as "restarting" | "retrying" | "offline"));
  else if (name === "updating") {
    link("live");
    build();
  } else if (name === "restart" || name === "update") {
    link("live");
    at(BEFORE_MS, () => link("restarting"));
    at(BEFORE_MS + OUTAGE_MS, () => {
      link("live");
      if (name === "update") build();
    });
  } else if (name === "drop") {
    link("live");
    at(BEFORE_MS, () => link("retrying"));
    at(BEFORE_MS + lostMs, () => link("offline"));
    at(BEFORE_MS + lostMs + OUTAGE_MS, () => link("live"));
  }
  return () => timers.forEach(clearTimeout);
}
