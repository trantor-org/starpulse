import { useEffect } from "react";

/** The User Timing mark for the first frame that shows the Board; `bench/page_latency.py` reads it as the page's first paint. */
export const BOARD_DRAWN = "starpulse:board-drawn";

/** Marks the frame after `ready` first turns true (the commit that shows the Board has run by then), once per page. */
export function useBoardDrawn(ready: boolean): void {
  useEffect(() => {
    if (!ready || performance.getEntriesByName(BOARD_DRAWN).length) return;
    requestAnimationFrame(() => {
      if (!performance.getEntriesByName(BOARD_DRAWN).length) performance.mark(BOARD_DRAWN);
    });
  }, [ready]);
}
