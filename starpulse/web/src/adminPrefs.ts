// The Admin view's per-browser choices, kept in localStorage like the Kanban's and the navigator's fold. Font size is the first: one scale
// that every CSS font size multiplies through `--fs` and the renderer applies to its canvas labels.
import { browserStorage, type FoldStorage } from "./nav";

export const ADMIN_KEY = "fv.admin.prefs";
/** The font size range in percent; the slider steps by `step` and the tick buttons jump to `ticks`. */
export const SCALE = { min: 85, max: 150, step: 5, def: 100, ticks: [85, 100, 115, 130, 150] } as const;

export interface AdminPrefs {
  /** The font size in percent of the design size. */
  scale: number;
}
export type StyleRoot = { style: { setProperty(name: string, value: string): void } };

/** `v` as a legal scale: a number held to the range and snapped to a step, anything else 100. */
export function clampScale(v: unknown): number {
  if (typeof v !== "number" || !Number.isFinite(v)) return SCALE.def;
  const snapped = Math.round(v / SCALE.step) * SCALE.step;
  return Math.min(SCALE.max, Math.max(SCALE.min, snapped));
}

/** What the last visit kept; absent, unreadable or out-of-range storage gives the design size. */
export function loadAdmin(storage: FoldStorage | null): AdminPrefs {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(ADMIN_KEY) ?? "null");
    const scale = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>).scale : undefined;
    return { scale: clampScale(scale) };
  } catch {
    return { scale: SCALE.def };
  }
}

export function saveAdmin(storage: FoldStorage | null, p: AdminPrefs): void {
  try {
    storage?.setItem(ADMIN_KEY, JSON.stringify(p));
  } catch {
    // storage is off: the choice lasts the session
  }
}

/** Publish the scale as `--fs`, the factor style.css multiplies every font size by. */
export const applyScale = (scale: number, root: StyleRoot): void => root.style.setProperty("--fs", String(+(scale / 100).toFixed(2)));

/** A canvas label's font size: fixed on screen whatever the zoom `k`, and scaled with the page's text. */
export const labelPx = (size: number, k: number, scale: number): number => (size * scale) / 100 / k;

export class AdminStore {
  private prefs: AdminPrefs;
  private listeners = new Set<() => void>();

  constructor(private storage: FoldStorage | null = browserStorage(), private root: StyleRoot = document.documentElement) {
    this.prefs = loadAdmin(storage);
    applyScale(this.prefs.scale, root);
  }

  get = () => this.prefs;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  setScale(v: number) {
    this.set({ scale: clampScale(v) });
  }
  reset() {
    this.set({ scale: SCALE.def });
  }
  private set(next: AdminPrefs) {
    if (next.scale === this.prefs.scale) return;
    this.prefs = next;
    applyScale(next.scale, this.root);
    saveAdmin(this.storage, next);
    for (const fn of this.listeners) fn();
  }
}
