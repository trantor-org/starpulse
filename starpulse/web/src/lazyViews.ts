// The views the Board does not draw first, each loaded the first time it is shown. The entry chunk then evaluates only what the
// Board draws; `prefetchViews` fetches the rest once the Board is on screen, so the first switch to a view finds it loaded.
// The one-file build (`vite build --mode one-file`, for the demo) bundles these imports into its single script.
import { lazy } from "react";

const load = {
  kanban: () => import("./features/kanban/Kanban"),
  dags: () => import("./features/dags/Dags"),
  admin: () => import("./AdminPage"),
  orbit: () => import("./features/orbit/OrbitCard"),
};

export const Kanban = lazy(async () => ({ default: (await load.kanban()).Kanban }));
export const Dags = lazy(async () => ({ default: (await load.dags()).Dags }));
export const AdminPage = lazy(async () => ({ default: (await load.admin()).AdminPage }));
export const OrbitCard = lazy(async () => ({ default: (await load.orbit()).OrbitCard }));

/** Starts loading every view not loaded yet, when the browser has nothing else to do. Returns the cancel. */
export function prefetchViews(): () => void {
  const go = () => Object.values(load).forEach((l) => void l());
  if (typeof requestIdleCallback === "function") {
    const id = requestIdleCallback(go, { timeout: 2000 });
    return () => cancelIdleCallback(id);
  }
  const id = setTimeout(go, 200);
  return () => clearTimeout(id);
}
