// The left navigator panel's fold and the canvas's share of the page beside it.
// One fold setting serves every view, so it lives here rather than in a view.
export const FOLD_KEY = "fv.nav.folded";

/** How long the panel takes to fold, in ms: the canvas refits every frame for as long as its CSS width transition (.3s in style.css) runs. */
export const FOLD_MS = 300;

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

/** The canvas's left edge and width: the page between the panel and the rail. */
export const canvasSpace = (viewport: number, nav: number, rail: number) => ({ left: nav, width: viewport - nav - rail });

export type ViewName = "constellation" | "kanban" | "admin";

/** The view an address opens: the Kanban or Admin only when it says so. */
export function viewOf(search: string): ViewName {
  const v = new URLSearchParams(search).get("view");
  return v === "kanban" || v === "admin" ? v : "constellation";
}

/** The query string that opens `view`, keeping every other parameter. */
export function viewSearch(search: string, view: ViewName): string {
  const params = new URLSearchParams(search);
  params.delete("view");
  if (view !== "constellation") params.set("view", view);
  return queryString(params);
}

/** `params` as an address's query string, a parameter with no value written bare. */
export function queryString(params: URLSearchParams): string {
  const text = params.toString().replace(/=(?=&|$)/g, "");
  return text ? `?${text}` : "";
}
