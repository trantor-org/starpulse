import { useEffect, useState } from "react";

/** The User Timing mark for the first frame that shows the Board; `bench/page_latency.py` reads it as the page's first paint. */
export const BOARD_DRAWN = "starpulse:board-drawn";

/** How long a page that has received no board waits before it stops holding back what the Board does not need. */
const NO_BOARD_MS = 2000;

const drawn = () => performance.getEntriesByName(BOARD_DRAWN).length > 0;

/** Marks the frame after `ready` first turns true (the commit that shows the Board has run by then), once per page.
 *  Returns whether the Board has been drawn, or has failed to arrive for `NO_BOARD_MS`: the parts of the page the Board's
 *  first frame does not need mount then, so they are not in the way of it. */
export function useBoardDrawn(ready: boolean): boolean {
  const [done, setDone] = useState(drawn);
  useEffect(() => {
    if (!ready || drawn()) return;
    requestAnimationFrame(() => {
      if (!drawn()) performance.mark(BOARD_DRAWN);
      setDone(true);
    });
  }, [ready]);
  useEffect(() => {
    const t = setTimeout(() => setDone(true), NO_BOARD_MS);
    return () => clearTimeout(t);
  }, []);
  return done;
}
