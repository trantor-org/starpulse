// The Admin view's per-browser choices, kept in localStorage like the Kanban's and the navigator's fold. Font size is one scale that
// every CSS font size multiplies through `--fs` and the renderer applies to its canvas labels; Motion, Opens on, Kanban cards and Clock
// follow it under the same key.
import type { ClockMode } from "../../shared/clock";
import { browserStorage, type FoldStorage, type ViewName } from "../../shared/nav";

export const ADMIN_KEY = "fv.admin.prefs";
/** The font size range in percent; the slider steps by `step` and the tick buttons jump to `ticks`. */
export const SCALE = { min: 85, max: 150, step: 5, def: 100, ticks: [85, 100, 115, 130, 150] } as const;

export type Density = "comfortable" | "compact";
/** The views a bare address can open. */
export type OpensOn = Exclude<ViewName, "admin">;

export interface AdminPrefs {
  /** The font size in percent of the design size. */
  scale: number;
  /** Off stills CSS animation and transitions and slows the Star Map's frame loop. */
  motion: boolean;
  /** The view an address with no `view` parameter opens. */
  view: OpensOn;
  density: Density;
  clock: ClockMode;
}
export const ADMIN_DEFAULTS: AdminPrefs = { scale: SCALE.def, motion: true, view: "constellation", density: "comfortable", clock: "24" };
export type StyleRoot = { style: { setProperty(name: string, value: string): void }; classList: { toggle(name: string, force?: boolean): unknown } };

/** `v` when it is one of `allowed`, else `fallback`. */
const oneOf = <T extends string>(v: unknown, allowed: readonly T[], fallback: T): T => (allowed.includes(v as T) ? (v as T) : fallback);

/** `v` as a legal scale: a number held to the range and snapped to a step, anything else 100. */
export function clampScale(v: unknown): number {
  if (typeof v !== "number" || !Number.isFinite(v)) return SCALE.def;
  const snapped = Math.round(v / SCALE.step) * SCALE.step;
  return Math.min(SCALE.max, Math.max(SCALE.min, snapped));
}

/** What the last visit kept; absent, unreadable or unknown values give the defaults. */
export function loadAdmin(storage: FoldStorage | null): AdminPrefs {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(ADMIN_KEY) ?? "null");
    const r = typeof raw === "object" && raw !== null ? (raw as Record<string, unknown>) : {};
    return {
      scale: clampScale(r.scale),
      motion: typeof r.motion === "boolean" ? r.motion : ADMIN_DEFAULTS.motion,
      view: oneOf(r.view, ["constellation", "kanban"], ADMIN_DEFAULTS.view),
      density: oneOf(r.density, ["comfortable", "compact"], ADMIN_DEFAULTS.density),
      clock: oneOf(r.clock, ["24", "12"], ADMIN_DEFAULTS.clock),
    };
  } catch {
    return ADMIN_DEFAULTS;
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

/** Publish the motion choice as the `still` class, which style.css reads to stop every animation and transition. */
export const applyMotion = (motion: boolean, root: StyleRoot): void => void root.classList.toggle("still", !motion);

/** A canvas label's font size: fixed on screen whatever the zoom `k`, and scaled with the page's text. */
export const labelPx = (size: number, k: number, scale: number): number => (size * scale) / 100 / k;

export class AdminStore {
  private prefs: AdminPrefs;
  private listeners = new Set<() => void>();

  constructor(private storage: FoldStorage | null = browserStorage(), private root: StyleRoot = document.documentElement) {
    this.prefs = loadAdmin(storage);
    applyScale(this.prefs.scale, root);
    applyMotion(this.prefs.motion, root);
  }

  get = () => this.prefs;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  setScale(v: number) {
    this.set({ ...this.prefs, scale: clampScale(v) });
  }
  setMotion(motion: boolean) {
    this.set({ ...this.prefs, motion });
  }
  setView(view: OpensOn) {
    this.set({ ...this.prefs, view });
  }
  setDensity(density: Density) {
    this.set({ ...this.prefs, density });
  }
  setClock(clock: ClockMode) {
    this.set({ ...this.prefs, clock });
  }
  reset() {
    this.set(ADMIN_DEFAULTS);
  }
  private set(next: AdminPrefs) {
    if ((Object.keys(next) as (keyof AdminPrefs)[]).every((k) => next[k] === this.prefs[k])) return;
    this.prefs = next;
    applyScale(next.scale, this.root);
    applyMotion(next.motion, this.root);
    saveAdmin(this.storage, next);
    for (const fn of this.listeners) fn();
  }
}
