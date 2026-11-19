// The views the Board does not draw first, each loaded the first time it is shown. The entry chunk then evaluates only what the
// Board draws; `prefetchViews` fetches the rest once the Board is on screen, so the first switch to a view finds it loaded.
import { lazy } from "react";

const load = {
  kanban: () => import("./features/kanban/Kanban"),
  dags: () => import("./features/dags/Dags"),
  admin: () => import("./AdminPage"),
  drill: () => import("./features/level/SunsDrillIn"),
};

export const Kanban = lazy(async () => ({ default: (await load.kanban()).Kanban }));
export const Dags = lazy(async () => ({ default: (await load.dags()).Dags }));
export const AdminPage = lazy(async () => ({ default: (await load.admin()).AdminPage }));
/** The In Progress drill-in, prefetched with the views so the first click on the In Progress sun finds it loaded. */
export const SunsDrillIn = lazy(async () => ({ default: (await load.drill()).SunsDrillIn }));

/** Starts loading every view not loaded yet, when the browser has nothing else to do. Returns the cancel. */
export function prefetchViews(): () => void {
  const go = () => {
    Object.values(load).forEach((l) => void l());
    warmBadgeGlyphs();
  };
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(go, { timeout: 2000 });
    return () => cancelIdleCallback(id);
  }
  const id = setTimeout(go, 200);
  return () => clearTimeout(id);
}

/** The Kanban badges (⌁ ⧗ ⛓) are in none of the bundled fonts, and the first text to use one pays the system's fallback-font lookup. Lay them out once here, off screen, so the Kanban first open does not. */
function warmBadgeGlyphs(): void {
  const probe = document.createElement("div");
  probe.setAttribute("aria-hidden", "true");
  probe.style.cssText = "position:fixed;left:-9999px;visibility:hidden;pointer-events:none";
  probe.innerHTML = "<span>⌁ ⧗ ⛓</span><span style=\"font-family:'JetBrains Mono',monospace\">⌁ ⧗ ⛓</span>";
  document.body.append(probe);
  probe.getBoundingClientRect();
  probe.remove();
}
