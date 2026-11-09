// A scrolling box marks itself while it scrolls, so the rows that pass under a still pointer can stand aside.
import { useEffect, type RefObject } from "react";

/** Milliseconds a box rests after its last scroll before its rows take the pointer again. */
const SCROLL_REST_MS = 300;

/** Gives each box under `ref` matching `boxes` the class `scrolling` until it has rested, on the element, not in state, so the scroll draws nothing. */
export function useScrollRest(ref: RefObject<HTMLElement | null>, boxes: string) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const rests = new Map<Element, ReturnType<typeof setTimeout>>();
    const onScroll = (e: Event) => {
      const box = e.target as Element;
      if (!box.matches?.(boxes)) return;
      box.classList.add("scrolling");
      clearTimeout(rests.get(box));
      // the rest ends at a frame, after that frame's scroll events: a long task that outlasts it cannot end it mid-scroll
      const rest = setTimeout(() => requestAnimationFrame(() => {
        if (rests.get(box) !== rest) return;
        box.classList.remove("scrolling");
        rests.delete(box);
      }), SCROLL_REST_MS);
      rests.set(box, rest);
    };
    el.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => { el.removeEventListener("scroll", onScroll, { capture: true }); rests.forEach(clearTimeout); rests.clear(); };
  }, [ref, boxes]);
}
