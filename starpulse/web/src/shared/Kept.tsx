// A view that stays mounted once it has been opened. Switching views then shows a view that is already built and laid
// out, instead of unmounting one and mounting the next (the Kanban lays out thousands of objects each time it mounts).
import { createContext, startTransition, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

const ViewActive = createContext(true);
const keptViews = new Map<string, HTMLElement>();
const keptFades = new WeakMap<HTMLElement, Animation>();
let revealedView: string | null = null;
const PREPAINT_OPACITY = 0.001;

/** Runs after `count` painted frames; the disposer cancels whichever frame is next. */
const afterFrames = (count: number, run: () => void) => {
  let id = 0;
  const next = () => count-- > 1 ? void (id = requestAnimationFrame(next)) : run();
  id = requestAnimationFrame(next);
  return () => cancelAnimationFrame(id);
};

/** Settles once every view warmed so far is laid out: views warm one after another, each in tasks of its own. */
let warmed = Promise.resolve();

/** Whether the view this is read in is the one showing: a hidden view stops its timers, fetches and animation loops. */
export const useViewActive = () => useContext(ViewActive);
/** Whether an imperatively revealed kept surface is visible, before React reconciles the view state. */
export const isKeptRevealed = (name: string) => revealedView === name;

const setSurfaceOpacity = (view: HTMLElement, opacity: number) => {
  const surface = view.firstElementChild;
  if (!(surface instanceof HTMLElement)) return;
  let fade = keptFades.get(surface);
  if (!fade && surface.animate) {
    fade = surface.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 1, fill: "both" });
    fade.pause();
    keptFades.set(surface, fade);
  }
  if (fade) fade.currentTime = opacity;
  else surface.style.opacity = String(opacity);
};

const showSurface = (view: HTMLElement, shown: boolean) => setSurfaceOpacity(view, shown ? 1 : 0);

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
 *  the stylesheet makes its already-laid-out root transparent and pauses its known looping animations.
 *  Left, it is made inert in the click's own render and learns it is inactive in a transition after it.
 *  Shown again, the view first appears as it was left, so the frame after the click only unhides it; after the reveal
 *  window it goes live and renders the latest children. A quick switch back cancels the pending inactive render.
 *  `warm` mounts a view that has not been shown yet, hidden and inactive, in a transition React can break into tasks a
 *  frame long; its first showing is then a later showing, so the click that opens it only unhides it. While hidden it is
 *  laid out unseen once its code has loaded, one child of its `[data-warm-parts]` element a frame (the stylesheet skips the rest). Views warm one at a time. */
export function Kept({ name, on, warm = false, children }: { name?: string; on: boolean; warm?: boolean; children: ReactNode }) {
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
    if (warming === null) {
      if (shown === null) return;
      const view = box.current;
      if (!on && view) {
        // A non-zero but sub-pixel alpha makes Chrome raster the promoted surface while it is warming; later reveals
        // can then change only the compositor animation's current time instead of painting the whole view.
        setSurfaceOpacity(view, PREPAINT_OPACITY);
        const cancel = afterFrames(2, () => {
          showSurface(view, false);
          release.current?.();
        });
        return () => { cancel(); release.current?.(); };
      }
      return void release.current?.();
    }
    let id = 0;
    const step = () => {
      const el = box.current;
      if (el && !el.childElementCount) return void (id = requestAnimationFrame(step)); // its code is still loading
      const parts = el?.querySelector("[data-warm-parts]")?.children.length ?? 0;
      setWarming(warming < parts ? warming + 1 : null);
    };
    id = requestAnimationFrame(step);
    return () => cancelAnimationFrame(id);
  }, [on, warming, shown]);
  useEffect(() => () => release.current?.(), []);
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
  return <div ref={box} className="kept" inert={!on} data-view={name} data-warm={warming ?? undefined}><ViewActive value={live}>{shown}</ViewActive></div>;
}
