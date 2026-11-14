/** The User Timing mark for a modal's frame once it shows its full content; `bench/ui_smoke.py` reads it, its `detail.label` naming the dialog. */
export const MODAL_DRAWN = "starpulse:modal-drawn";

const READY = '[role="dialog"]:not([aria-busy="true"])';
const HELD_BACK = "[inert], [hidden]";

/** Marks each dialog the frame after it is in the page, visible and no longer busy, once per element; returns the stop. */
export function watchModalMarks(root: Element = document.body): () => void {
  const marked = new WeakSet<Element>();
  const scan = () => {
    for (const dialog of root.querySelectorAll(READY)) {
      if (marked.has(dialog) || dialog.closest(HELD_BACK)) continue;
      marked.add(dialog);
      const label = dialog.getAttribute("aria-label") ?? "";
      requestAnimationFrame(() => requestAnimationFrame(() => performance.mark(MODAL_DRAWN, { detail: { label } })));
    }
  };
  const observer = new MutationObserver(scan);
  observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ["aria-busy", "inert", "hidden"] });
  scan();
  return () => observer.disconnect();
}
