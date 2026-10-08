// A view's filters kept in the browser, so each view opens on the filters it last had.
import { useEffect, useState } from "react";
import { browserStorage, type PrefStorage } from "./nav";

export const DAG_PREFS_KEY = "fv.dags.prefs", STARMAP_PREFS_KEY = "fv.starmap.prefs";

export type DagFilters = { q: string; only: string | null; dom: string | null; win: string | null };
export const NO_DAG_FILTERS: DagFilters = { q: "", only: null, dom: null, win: null };
export type StarmapFilters = { query: string };
export const NO_STARMAP_FILTERS: StarmapFilters = { query: "" };

/** What `storage` kept under `key`, field by field: a field missing or of another type than `fallback`'s keeps the fallback. */
export function loadFilters<T extends Record<string, string | null>>(storage: PrefStorage | null, key: string, fallback: T): T {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(key) ?? "null");
    if (typeof raw !== "object" || raw === null) return fallback;
    const o = raw as Record<string, unknown>, out: Record<string, string | null> = { ...fallback };
    for (const k of Object.keys(fallback)) {
      const v = o[k];
      if (typeof v === "string" || (v === null && fallback[k] === null)) out[k] = v;
    }
    return out as T;
  } catch {
    return fallback;
  }
}

export function saveFilters(storage: PrefStorage | null, key: string, filters: Record<string, string | null>): void {
  try {
    storage?.setItem(key, JSON.stringify(filters));
  } catch {
    // storage is off: the filters last the session
  }
}

/** A view's filters as state, read from the browser on mount and written back on each change. */
export function useFilters<T extends Record<string, string | null>>(key: string, fallback: T, storage: PrefStorage | null = browserStorage()) {
  const [filters, setFilters] = useState(() => loadFilters(storage, key, fallback));
  useEffect(() => saveFilters(storage, key, filters), [storage, key, filters]);
  return [filters, (patch: Partial<T>) => setFilters((f) => ({ ...f, ...patch }))] as const;
}
