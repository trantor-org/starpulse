// The left navigator panel's fold and the canvas's share of the page beside it.
// One fold setting serves every view, so it lives here rather than in a view.
export const FOLD_KEY = "fv.nav.folded";

export type FoldStorage = Pick<Storage, "getItem" | "setItem">;

// Browser storage can be absent (a private window); the fold then lasts the session.
export const browserStorage = (): FoldStorage | null => {
  try {
    return localStorage;
  } catch {
    return null;
  }
};

export class FoldStore {
  private folded: boolean;
  private listeners = new Set<() => void>();

  constructor(private storage: FoldStorage | null = browserStorage()) {
    try {
      this.folded = storage?.getItem(FOLD_KEY) === "1";
    } catch {
      this.folded = false;
    }
  }

  get = () => this.folded;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  toggle() {
    this.folded = !this.folded;
    try {
      this.storage?.setItem(FOLD_KEY, this.folded ? "1" : "0");
    } catch {
      // storage is off: the fold lasts the session
    }
    for (const fn of this.listeners) fn();
  }
  /** `[` folds or opens the panel, except while a field is taking text. */
  onKey(e: { key: string; target: unknown }) {
    const tag = (e.target as { tagName?: string } | null)?.tagName;
    if (e.key === "[" && tag !== "INPUT" && tag !== "TEXTAREA") this.toggle();
  }
}

/**
 * The canvas and the box its level is fitted in, from the panel's open and folded widths, never its current one:
 * the canvas spans the page the folded panel leaves, and the level fits between the open panel and the rail,
 * `inset` from the canvas's left edge. A fold only covers or uncovers sky; no body moves.
 */
export const canvasSpace = (viewport: number, nav: { open: number; fold: number }, rail: number) => ({
  left: nav.fold,
  width: viewport - nav.fold - rail,
  inset: nav.open - nav.fold,
  fitWidth: viewport - nav.open - rail,
});

export type ViewName = "constellation" | "kanban" | "admin" | "graph";

/** Whether the address is a retired per-graph one (`/board`, `/flow/<name>`, `/#sec-<name>`): those open the Star Map whatever "Opens on" says. */
export const retired = (pathname: string, hash: string) => pathname !== "/" || hash !== "";

/** The view an address opens: the one it names, or `fallback` (the Admin's "Opens on") when it names none. */
export function viewOf(search: string, fallback: ViewName = "constellation"): ViewName {
  const v = new URLSearchParams(search).get("view");
  if (v === null) return fallback;
  return v === "kanban" || v === "admin" || v === "graph" ? v : "constellation";
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
