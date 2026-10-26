// The page's first frame does not wait for React. index.html carries the frames the renderer draws into (the canvas, the two
// asides, the crumb, the tip and the panel), so this starts the renderer against them from the entry chunk; the React page, a chunk
// of its own, mounts after that frame and adopts what is held here.
import { AdminStore } from "./features/admin/adminPrefs";
import { HudStore } from "./render/hud";
import { loadLateFonts } from "./render/fonts";
import { renderer } from "./render/renderer";
import type { Renderer } from "./render/rendererTypes";
import { NO_BOARD_MS, markDrawn } from "./shared/boardMark";
import { onPhone, retired, shownView, viewOf } from "./shared/nav";

/** What the page adopts from its boot. */
export interface Booted {
  store: HudStore;
  admin: AdminStore;
  renderer: Renderer;
  canvas: HTMLCanvasElement;
  tip: HTMLDivElement;
  panel: HTMLDivElement;
}

let held: Booted | null = null;

/** The renderer and stores the boot started, or null on a page that was not booted (a test mounting the page itself). */
export const booted = () => held;

const frameOf = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/** Starts the Board and calls `mount` to bring up the React page once the first frame has been marked, or when no board comes. */
export function boot(mount: () => void): Booted {
  const canvas = frameOf<HTMLCanvasElement>("c"), tip = frameOf<HTMLDivElement>("tip"), panel = frameOf<HTMLDivElement>("panel");
  const admin = new AdminStore(), store = new HudStore();
  // a bare address opens the view the Admin chose; one that names a view opens that, and a view that covers the map leaves it undrawn;
  // a phone width has no Star Map, so it opens the Kanban whatever the address or the Admin chose
  const wanted = viewOf(location.search, retired(location.pathname, location.hash) ? "constellation" : admin.get().view);
  const star = shownView(wanted, onPhone()) === "constellation";
  let mounted = false;
  const open = () => {
    if (mounted) return;
    mounted = true;
    mount();
  };
  // the draw's own frame: the mark is the page's first paint, and the page mounts a frame behind it
  const drawn = () => {
    markDrawn();
    void loadLateFonts(); // Inter 500 and JetBrains: chrome after the board, not on the critical path
    requestAnimationFrame(open);
  };
  const r = renderer(canvas, store, { tip, panel }, new URLSearchParams(location.search).has("demo"), admin.get, star ? drawn : undefined);
  held = { store, admin, renderer: r, canvas, tip, panel };
  r.start();
  if (!star) {
    for (const el of [canvas, tip, panel, frameOf("crumb")]) el.classList.add("off");
    r.show(false);
    const unsubscribe = store.subscribe(() => {
      if (store.get().tree === null) return;
      unsubscribe();
      requestAnimationFrame(() => {
        markDrawn();
        void loadLateFonts();
        open();
      });
    });
  }
  setTimeout(open, NO_BOARD_MS);
  return held;
}

