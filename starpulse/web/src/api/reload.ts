// A page left open keeps running the build it loaded. Once the server names another build, the page reloads onto it when nobody is using it.

/** How long without pointer, key or wheel input the page counts as left alone. */
export const IDLE_MS = 30_000;
const CHECK_MS = 1000;
const INPUTS = ["pointerdown", "pointermove", "keydown", "wheel"] as const;
/** The build the page last reloaded for, which a reload keeps. */
const RELOADED = "starpulse.reloadedFor";
/** Each thing the page opens over the Board: a task view or other dialog, and a menu that is shown. */
const OPEN = '[role="dialog"], dialog[open], [role="menu"]:not([hidden])';

/** What the page is doing, as the reload reads it; `domPage` is the browser's. */
export interface Page {
  now(): number;
  /** A task view, dialog or menu is open, or a field has focus. */
  busy(): boolean;
  /** The tab is in the background. */
  hidden(): boolean;
  /** `fn` runs on every pointer, key or wheel input; the function returned stops that. */
  onInput(fn: () => void): () => void;
  /** `fn` runs when the tab is shown or hidden; the function returned stops that. */
  onVisibility(fn: () => void): () => void;
  reload(): void;
  /** The build a reload was last made for, which survives that reload. */
  reloaded: { get(): string | null; set(build: string): void };
}

const fieldFocused = () => {
  const el = document.activeElement as HTMLElement | null;
  return !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
};

export const domPage = (): Page => ({
  now: () => Date.now(),
  busy: () => !!document.querySelector(OPEN) || fieldFocused(),
  hidden: () => document.hidden,
  onInput(fn) {
    for (const type of INPUTS) addEventListener(type, fn, { capture: true, passive: true });
    return () => INPUTS.forEach((type) => removeEventListener(type, fn, { capture: true }));
  },
  onVisibility(fn) {
    document.addEventListener("visibilitychange", fn);
    return () => document.removeEventListener("visibilitychange", fn);
  },
  reload: () => location.reload(),
  reloaded: {
    get() {
      try {
        return sessionStorage.getItem(RELOADED);
      } catch {
        return null; // storage off: the page cannot tell it already reloaded, so it keeps the one reload it makes per page load
      }
    },
    set(build) {
      try {
        sessionStorage.setItem(RELOADED, build);
      } catch {
        /* storage off */
      }
    },
  },
});

/**
 * Reload the page onto `build` once it is idle: no task view, dialog or menu open, no field focused, and no input for IDLE_MS; a
 * hidden tab is idle at once. It reloads once per build: a page that finds the build still differs after the reload it made
 * does not reload again. The function returned cancels it.
 */
export function reloadWhenIdle(build: string, page: Page = domPage()): () => void {
  if (page.reloaded.get() === build) return () => {};
  let lastInput = page.now();
  const offInput = page.onInput(() => void (lastInput = page.now()));
  const stop = () => {
    clearInterval(timer);
    offInput();
    offVisibility();
  };
  const check = () => {
    if (!page.hidden() && (page.busy() || page.now() - lastInput < IDLE_MS)) return;
    stop();
    page.reloaded.set(build);
    page.reload();
  };
  const offVisibility = page.onVisibility(check);
  const timer = setInterval(check, CHECK_MS);
  check();
  return stop;
}
