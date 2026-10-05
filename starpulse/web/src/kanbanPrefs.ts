// The Kanban view's choices kept in the browser: filters, hidden items and folds survive a reload, and an address that names filters starts from them instead.
import { NO_PREFS, type Prefs } from "./kanban";
import { queryString, type FoldStorage } from "./nav";

export const PREFS_KEY = "fv.kanban.prefs";
/** The address parameters a deep link filters by; a bare `assignee` or `milestone` means the unassigned or No milestone. */
const LINK = ["q", "assignee", "milestone"] as const;

const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const textOrNull = (v: unknown) => (typeof v === "string" ? v : null);

function stored(storage: FoldStorage | null): Prefs {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(PREFS_KEY) ?? "null");
    if (typeof raw !== "object" || raw === null) return NO_PREFS;
    const o = raw as Record<string, unknown>;
    return {
      query: typeof o.query === "string" ? o.query : "", assignee: textOrNull(o.assignee), milestone: textOrNull(o.milestone),
      folded: new Set(strings(o.folded)), hiddenMilestones: new Set(strings(o.hiddenMilestones)), hiddenTasks: new Set(strings(o.hiddenTasks)),
    };
  } catch {
    return NO_PREFS;
  }
}

/** The view's starting state: the address's own filters when it names any (nothing hidden or folded), else what the last visit kept. */
export function loadPrefs(storage: FoldStorage | null, search: string): Prefs {
  const params = new URLSearchParams(search);
  if (!LINK.some((k) => params.has(k))) return stored(storage);
  return { ...NO_PREFS, query: params.get("q") ?? "", assignee: params.get("assignee"), milestone: params.get("milestone") };
}

export function savePrefs(storage: FoldStorage | null, p: Prefs): void {
  const { query, assignee, milestone } = p;
  try {
    storage?.setItem(PREFS_KEY, JSON.stringify({ query, assignee, milestone, folded: [...p.folded], hiddenMilestones: [...p.hiddenMilestones], hiddenTasks: [...p.hiddenTasks] }));
  } catch {
    // storage is off: the choices last the session
  }
}

/** The task a `task` link opens the view on, its modal shown over the board. */
export const linkedTask = (search: string): string | null => new URLSearchParams(search).get("task");

/** The address once the view has taken a deep link's filters and task, so a reload keeps what the operator changed since. */
export function withoutFilters(search: string): string {
  const params = new URLSearchParams(search);
  for (const k of [...LINK, "task"]) params.delete(k);
  return queryString(params);
}
