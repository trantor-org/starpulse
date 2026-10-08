// A view that stays mounted once it has been opened. Switching views then shows a view that is already built and laid
// out, instead of unmounting one and mounting the next (the Kanban lays out thousands of objects each time it mounts).
import { createContext, useContext, useState, type ReactNode } from "react";

const ViewActive = createContext(true);

/** Whether the view this is read in is the one showing: a hidden view stops its timers, fetches and animation loops. */
export const useViewActive = () => useContext(ViewActive);

/** Mounts `children` the first time `on` is true and keeps them mounted. While `on` is false it keeps the last element it was
 *  given, so React skips the view when the parent renders; the wrapper is `inert` (no focus, clicks or screen-reader reach) and
 *  the stylesheet skips its rendering (`content-visibility: hidden`). */
export function Kept({ on, children }: { on: boolean; children: ReactNode }) {
  const [shown, setShown] = useState<ReactNode>(on ? children : null);
  if (on && shown !== children) setShown(children);
  if (shown === null) return null;
  return <div className="kept" inert={!on}><ViewActive value={on}>{shown}</ViewActive></div>;
}
