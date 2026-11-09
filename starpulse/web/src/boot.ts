// The page's first frame does not wait for React. index.html carries the frames the renderer draws into (the canvas, the two
// asides, the crumb, the tip and the panel), so this starts the renderer against them from the entry chunk; the React page, a chunk
// of its own, mounts after that frame and adopts what is held here.
import { AdminStore } from "./features/admin/adminPrefs";
import { applyTheme } from "./features/admin/theme/apply";
import { ThemeStore } from "./features/admin/theme/themeStore";
import { linkedTask } from "./features/kanban/kanbanPrefs";
import { RecordCache } from "./features/kanban/taskViewModel";
import { HudStore } from "./render/hud";
import { loadHudViews } from "./render/hudViews";
import { loadLateFonts } from "./render/fonts";
import { renderer } from "./render/renderer";
import type { Renderer } from "./render/rendererTypes";
import { NO_BOARD_MS, markDrawn } from "./shared/boardMark";
import { onPhone, renamedView, retired, shownView, viewOf, type ViewName } from "./shared/nav";

/** What the page adopts from its boot. */
export interface Booted {
  store: HudStore;
  admin: AdminStore;
  theme: ThemeStore;
  /** The records read ahead, among them the one the address names, which the boot asks for before anything else. */
  records: RecordCache;
  renderer: Renderer;
  canvas: HTMLCanvasElement;
  tip: HTMLDivElement;
  panel: HTMLDivElement;
}

let held: Booted | null = null;

/** The renderer and stores the boot started, or null on a page that was not booted (a test mounting the page itself). */
export const booted = () => held;

const frameOf = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

/** Starts the Board and calls `mount` to bring up the React page once the first frame has been marked, or when no board comes.
 *  A page that opens on another view than the Star Map mounts at once and has `preload` fetch that view's chunk, beside the snapshot. */
export function boot(mount: () => void, preload?: (view: ViewName) => void): Booted {
  const canvas = frameOf<HTMLCanvasElement>("c"), tip = frameOf<HTMLDivElement>("tip"), panel = frameOf<HTMLDivElement>("panel");
  // the saved theme goes on :root here, before the first paint
  const admin = new AdminStore(), store = new HudStore(), theme = new ThemeStore(applyTheme);
  // a task the address names has its record read already, by index.html's head; failing that it is read now, not when its modal mounts
  // behind the snapshot and the page's other fetches
  const records = new RecordCache(), linked = linkedTask(location.search);
  const w = globalThis as { __earlyRecord?: { id: string; read: Promise<Response> } };
  const early = w.__earlyRecord;
  delete w.__earlyRecord;
  if (linked) records.readAhead(linked, early?.id === linked ? () => early.read : undefined);
  // the Jobs view was the DAGs view: an old address is rewritten to the new one in place
  const renamed = renamedView(location.search);
  if (renamed !== null) history.replaceState(null, "", `${location.pathname}${renamed}${location.hash}`);
  // a bare address opens the view the Admin chose; one that names a view opens that, and a view that covers the map leaves it undrawn;
  // a phone width has no Star Map, so it opens the Kanban whatever the address or the Admin chose
  const wanted = viewOf(location.search, retired(location.pathname, location.hash) ? "constellation" : admin.get().view);
  const shown = shownView(wanted, onPhone()), star = shown === "constellation";
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
  // no Star Map frame is in the way of another view, so the page, the view's chunk and the card models are asked for before the
  // renderer is built: their fetches run while it builds, not a round trip behind it
  if (!star) {
    open();
    preload?.(shown);
    void loadHudViews();
  }
  const r = renderer(canvas, store, { tip, panel }, new URLSearchParams(location.search).has("demo"), admin.get, star ? drawn : undefined);
  held = { store, admin, theme, records, renderer: r, canvas, tip, panel };
  r.start();
  if (!star) {
    for (const el of [canvas, tip, panel, frameOf("crumb")]) el.classList.add("off");
    r.show(false);
    // The page stays unseen until the first frame is marked, so its empty counts are never painted ahead of the snapshot
    const root = document.getElementById("root"), reveal = () => root?.style.removeProperty("visibility");
    root?.style.setProperty("visibility", "hidden");
    const unsubscribe = store.subscribe(() => {
      if (store.get().tree === null) return;
      unsubscribe();
      requestAnimationFrame(() => {
        markDrawn();
        reveal();
        void loadLateFonts();
      });
    });
    setTimeout(reveal, NO_BOARD_MS);
  }
  setTimeout(open, NO_BOARD_MS);
  return held;
}

