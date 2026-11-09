import { useEffect, useState } from "react";
import { BOARD_DRAWN, NO_BOARD_MS, drawn, markDrawn } from "./boardMark";

export { BOARD_DRAWN };

/** Marks the frame after `ready` first turns true (the commit that shows the Board has run by then), once per page.
 *  Returns whether the Board has been drawn, or has failed to arrive for `NO_BOARD_MS`: the parts of the page the Board's
 *  first frame does not need mount then, so they are not in the way of it. */
export function useBoardDrawn(ready: boolean): boolean {
  const [done, setDone] = useState(drawn);
  useEffect(() => {
    if (!ready || drawn()) return;
    requestAnimationFrame(() => {
      markDrawn();
      setDone(true);
    });
  }, [ready]);
  useEffect(() => {
    const t = setTimeout(() => setDone(true), NO_BOARD_MS);
    return () => clearTimeout(t);
  }, []);
  return done;
}
