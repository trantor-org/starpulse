// A view that stays mounted once it has been opened. Switching views then shows a view that is already built and laid
// out, instead of unmounting one and mounting the next (the Kanban lays out thousands of objects each time it mounts).
import { createContext, startTransition, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

const ViewActive = createContext(true);

/** Whether the view this is read in is the one showing: a hidden view stops its timers, fetches and animation loops. */
export const useViewActive = () => useContext(ViewActive);

/** Mounts `children` the first time `on` is true and keeps them mounted. While `on` is false it keeps the last element it was
 *  given, so React skips the view when the parent renders; the wrapper is `inert` (no focus, clicks or screen-reader reach),
 *  the stylesheet skips its rendering (`content-visibility: hidden`) and its running animations are paused.
 *  Shown again, the view first appears as it was left, so the frame after the click only unhides it; two frames later it
 *  goes live: it renders the latest children, learns it is active and plays the animations it paused. */
export function Kept({ on, children }: { on: boolean; children: ReactNode }) {
  const [shown, setShown] = useState<ReactNode>(on ? children : null);
  const [live, setLive] = useState(on);
  if (shown === null && on) {
    setShown(children); // a first showing mounts the latest children, so it is live at once
    setLive(true);
  }
  if (!on && live) setLive(false);
  if (on && live && shown !== children) setShown(children);
  useEffect(() => {
    if (!on || live) return;
    let id = requestAnimationFrame(() => (id = requestAnimationFrame(() => startTransition(() => setLive(true)))));
    return () => cancelAnimationFrame(id);
  }, [on, live]);
  // paused by script: a stylesheet rule cannot stop them, since a style change inside a skipped subtree waits until it is shown
  const box = useRef<HTMLDivElement>(null), paused = useRef<Animation[]>([]);
  useLayoutEffect(() => {
    if (!on) {
      paused.current = (box.current?.getAnimations?.({ subtree: true }) ?? []).filter((a) => a.playState === "running");
      for (const a of paused.current) a.pause();
    } else if (live) {
      for (const a of paused.current) a.play();
      paused.current = [];
    }
  }, [on, live]);
  if (shown === null) return null;
  return <div ref={box} className="kept" inert={!on}><ViewActive value={on && live}>{shown}</ViewActive></div>;
}
