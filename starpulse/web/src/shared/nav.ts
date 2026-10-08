// The browser storage every view keeps its settings in.
export type PrefStorage = Pick<Storage, "getItem" | "setItem">;

// Browser storage can be absent (a private window); settings then last the session.
export const browserStorage = (): PrefStorage | null => {
  try {
    return localStorage;
  } catch {
    return null;
  }
};

/** The canvas: the page between the navigator and the rail, where the level is fitted. */
export const canvasSpace = (viewport: number, nav: number, rail: number) => ({ left: nav, width: viewport - nav - rail });

export type ViewName = "constellation" | "kanban" | "dags" | "admin" | "graph";

/** Whether the address is a retired per-graph one (`/board`, `/flow/<name>`, `/#sec-<name>`): those open the Star Map whatever "Opens on" says. */
export const retired = (pathname: string, hash: string) => pathname !== "/" || hash !== "";

/** The view an address opens: the one it names, or `fallback` (the Admin's "Opens on") when it names none. */
export function viewOf(search: string, fallback: ViewName = "constellation"): ViewName {
  const v = new URLSearchParams(search).get("view");
  if (v === null) return fallback;
  return v === "kanban" || v === "dags" || v === "admin" || v === "graph" ? v : "constellation";
}

/** The query string that opens `view`, keeping every other parameter; the view a bare address opens (`fallback`) needs no parameter. */
export function viewSearch(search: string, view: ViewName, fallback: ViewName = "constellation"): string {
  const params = new URLSearchParams(search);
  params.delete("view");
  if (view !== fallback) params.set("view", view);
  return queryString(params);
}

/** `params` as an address's query string, a parameter with no value written bare. */
export function queryString(params: URLSearchParams): string {
  const text = params.toString().replace(/=(?=&|$)/g, "");
  return text ? `?${text}` : "";
}

/** What Escape, Backspace and a right-click undo next: the open panel, the focused row, the scroll, then a level up. */
export type Back = "panel" | "focus" | "scroll" | "up";

/** The next thing to undo, one per press, or null on the Board. `depth` is the path's length. */
export function backStep(at: { panel: boolean; focus: string | null; scrolled: boolean; depth: number }): Back | null {
  if (at.panel) return "panel";
  if (at.focus) return "focus";
  if (at.scrolled) return "scroll";
  return at.depth > 1 ? "up" : null;
}

/** The machine level and the row focused on it that an address names; each null when absent. */
export function levelParams(search: string): { open: string | null; focus: string | null } {
  const params = new URLSearchParams(search);
  return { open: params.get("open"), focus: params.get("focus") };
}

/** Rewrites the address's query in place, unless it already reads `search`: a history replace is a synchronous round trip to the browser process, tens of milliseconds on a loaded host. */
export function replaceSearch(at: { pathname: string; search: string; hash: string }, search: string, replace: (url: string) => void): void {
  if (search !== at.search) replace(at.pathname + search + at.hash);
}

/** The query string that reproduces a machine level and its focused row, keeping every other parameter. */
export function levelSearch(search: string, at: { open: string | null; focus: string | null }): string {
  const params = new URLSearchParams(search);
  params.delete("open");
  params.delete("focus");
  if (at.open) params.set("open", at.open);
  if (at.focus) params.set("focus", at.focus);
  return queryString(params);
}
