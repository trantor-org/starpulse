// A view that stays mounted once it has been opened. Switching views then shows a view that is already built and laid
// out, instead of unmounting one and mounting the next (the Kanban lays out thousands of objects each time it mounts).
import { createContext, startTransition, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

const ViewActive = createContext(true);
const keptViews = new Map<string, HTMLElement>();
let revealedView: string | null = null;

/** Runs after `count` painted frames; the disposer cancels whichever frame is next. */
const afterFrames = (count: number, run: () => void) => {
  let id = 0;
  const next = () => count-- > 1 ? void (id = requestAnimationFrame(next)) : run();
  id = requestAnimationFrame(next);
  return () => cancelAnimationFrame(id);
};

/** Whether the view this is read in is the one showing: a hidden view stops its timers, fetches and animation loops. */
export const useViewActive = () => useContext(ViewActive);

const showSurface = (view: HTMLElement, shown: boolean) => {
  const surface = view.firstElementChild;
  if (surface instanceof HTMLElement) surface.style.opacity = shown ? "1" : "0";
};

/** Reveals one named mounted view immediately; `null` reveals the Star Map behind all kept views. */
export function revealKept(name: string | null) {
  if (name !== null && !keptViews.has(name)) return false;
  if (name === revealedView) return true;
  const previous = revealedView === null ? null : keptViews.get(revealedView);
  if (previous) showSurface(previous, false);
  revealedView = name;
  if (name !== null) showSurface(keptViews.get(name)!, true);
  return true;
}

/** Mounts `children` the first time `on` is true and keeps them mounted. While `on` is false it keeps the last element it was
 *  given, so React skips the view when the parent renders; the wrapper is `inert` (no focus, clicks or screen-reader reach),
 *  the stylesheet makes its already-laid-out root transparent and skips its style and layout (`content-visibility: hidden`).
 *  Left, it is made inert in the click's own render and learns it is inactive in a transition after it.
 *  Shown again, the view first appears as it was left, so the frame after the click only unhides it; after the reveal
 *  window it goes live and renders the latest children. A quick switch back cancels the pending inactive render.
 *  A view never mounts before its first showing. */
export function Kept({ name, on, children }: { name?: string; on: boolean; children: ReactNode }) {
  const [shown, setShown] = useState<ReactNode>(on ? children : null);
  const [live, setLive] = useState(on);
  if (shown === null && on) {
    setShown(children); // a first showing mounts the latest children, so it is live at once
    setLive(true);
  }
  if (on && live && shown !== children) setShown(children);
  const box = useRef<HTMLDivElement>(null);
  const latest = useRef(children);
  useLayoutEffect(() => void (latest.current = children));
  useLayoutEffect(() => {
    const view = box.current;
    if (!name || !view) return;
    keptViews.set(name, view);
    return () => {
      if (keptViews.get(name) !== view) return;
      keptViews.delete(name);
      if (revealedView === name) revealedView = null;
    };
  }, [name, shown]);
  useLayoutEffect(() => {
    if (on && name) revealedView = name;
    if (box.current) showSurface(box.current, on);
  }, [name, on, shown]);
  useEffect(() => {
    if (!on && live) startTransition(() => setLive(false));
  }, [on, live]);
  useEffect(() => {
    if (!on || live) return;
    return afterFrames(2, () => startTransition(() => {
      setShown(latest.current);
      setLive(true);
    }));
  }, [on, live]);
  if (shown === null) return null;
  return <div ref={box} className="kept" inert={!on} data-view={name}><ViewActive value={live}>{shown}</ViewActive></div>;
}
