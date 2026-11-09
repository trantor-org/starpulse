/** The User Timing mark for the first frame that shows the Board; `bench/page_latency.py` reads it as the page's first paint. */
export const BOARD_DRAWN = "starpulse:board-drawn";

/** How long a page that has received no board waits before it stops holding back what the Board does not need. */
export const NO_BOARD_MS = 2000;

/** Whether the page has marked its first Board. */
export const drawn = () => performance.getEntriesByName(BOARD_DRAWN).length > 0;

/** Marks the first Board's frame, once per page. */
export function markDrawn() {
  if (!drawn()) performance.mark(BOARD_DRAWN);
}
