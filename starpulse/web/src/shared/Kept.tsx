// A view that stays mounted once it has been opened. Switching views then shows a view that is already built and laid
// out, instead of unmounting one and mounting the next (the Kanban lays out thousands of objects each time it mounts).
import { createContext, startTransition, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

const ViewActive = createContext(true);

/** Settles once every view warmed so far is laid out: views warm one after another, each in tasks of its own. */
let warmed = Promise.resolve();

/** Whether the view this is read in is the one showing: a hidden view stops its timers, fetches and animation loops. */
export const useViewActive = () => useContext(ViewActive);

/** Mounts `children` the first time `on` is true and keeps them mounted. While `on` is false it keeps the last element it was
 *  given, so React skips the view when the parent renders; the wrapper is `inert` (no focus, clicks or screen-reader reach),
 *  the stylesheet skips its rendering (`content-visibility: hidden`) and its running animations are paused.
 *  Left, it is made inert in the click's own render and learns it is inactive in a transition after it.
 *  Shown again, the view first appears as it was left, so the frame after the click only unhides it; two frames later it
 *  goes live: it renders the latest children, learns it is active and plays the animations it paused.
 *  `warm` mounts a view that has not been shown yet, hidden and inactive, in a transition React can break into tasks a
 *  frame long; its first showing is then a later showing, so the click that opens it only unhides it. While hidden it is
 *  laid out unseen once its code has loaded, one child of its `[data-warm-parts]` element a frame (the stylesheet skips the rest), and only then is its
 *  rendering skipped, which keeps that layout. Views warm one at a time. */
export function Kept({ on, warm = false, children }: { on: boolean; warm?: boolean; children: ReactNode }) {
  const [shown, setShown] = useState<ReactNode>(on ? children : null);
  const [live, setLive] = useState(on);
  if (shown === null && on) {
    setShown(children); // a first showing mounts the latest children, so it is live at once
    setLive(true);
  }
  if (on && live && shown !== children) setShown(children);
  const box = useRef<HTMLDivElement>(null);
  const cold = shown === null && warm, latest = useRef(children);
  useLayoutEffect(() => void (latest.current = children));
  // warming: the part of the view laid out so far, one more a frame, until the whole view is and its rendering is skipped
  const [warming, setWarming] = useState<number | null>(null);
  if (on && warming !== null) setWarming(null);
  const release = useRef<() => void>(undefined);
  useEffect(() => {
    if (!cold) return;
    let gone = false;
    const ahead = warmed;
    warmed = ahead.then(() => new Promise<void>((done) => (release.current = done)));
    let id: ReturnType<typeof setTimeout> | undefined;
    void ahead.then(() => {
      if (gone) return release.current?.();
      id = setTimeout(() => startTransition(() => { setShown((s) => s ?? latest.current); setWarming(0); }));
    });
    return () => { gone = true; clearTimeout(id); };
  }, [cold]);
  useEffect(() => {
    if (warming === null) return void (shown !== null && release.current?.());
    let id = 0;
    const step = () => {
      const el = box.current;
      if (el && !el.childElementCount) return void (id = requestAnimationFrame(step)); // its code is still loading
      const parts = el?.querySelector("[data-warm-parts]")?.children.length ?? 0;
      setWarming(warming < parts ? warming + 1 : null);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [warming, shown]);
  useEffect(() => () => release.current?.(), []);
  useEffect(() => {
    if (!on && live) startTransition(() => setLive(false));
  }, [on, live]);
  useEffect(() => {
    if (!on || live) return;
    let id = requestAnimationFrame(() => (id = requestAnimationFrame(() => startTransition(() => setLive(true)))));
    return () => cancelAnimationFrame(id);
  }, [on, live]);
  // paused by script: a stylesheet rule cannot stop them, since a style change inside a skipped subtree waits until it is shown
  const paused = useRef<Animation[]>([]);
  useLayoutEffect(() => {
    if (!on && live) { // the commit that leaves it, not the later one that tells it it is inactive
      // the document's list, not the box's: asking the box would lay out the subtree its own inert just stopped rendering
      const el = box.current;
      paused.current = (el ? document.getAnimations?.() ?? [] : []).filter((a) => a.playState === "running" && el!.contains((a.effect as KeyframeEffect | null)?.target ?? null));
      for (const a of paused.current) a.pause();
    } else if (live) {
      for (const a of paused.current) a.play();
      paused.current = [];
    }
  }, [on, live]);
  if (shown === null) return null;
  return <div ref={box} className="kept" inert={!on} data-warm={warming ?? undefined}><ViewActive value={live}>{shown}</ViewActive></div>;
}
