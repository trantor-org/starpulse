// The task view's model: the full record GET /api/task/<id> returns, and the Move to menu's keyboard.
import { ago, fmtAt } from "./clock";
import { apiFetch } from "./demo";
import type { KanbanTask } from "./kanban";

export interface Item { n: number; text: string; checked: boolean }

/** One Start Criterion of a task as the board reader evaluates it: `status` is `met`, `unmet`, `error` or `not evaluated`, and `checked` an ISO time. */
export interface StartCriterion {
  id: string;
  kind: string;
  expr: string;
  cmp: string | null;
  want: unknown;
  status: string;
  observed: unknown;
  error: string | null;
  checked: string | null;
}

/** Every field of a task the view draws that the snapshot's small entry does not carry. */
export interface TaskRecord {
  title: string;
  profile: string;
  priority: string;
  labels: string[];
  milestone: string;
  dependencies: string[];
  description: string;
  plan: string;
  notes: string;
  acceptanceCriteria: Item[];
  definitionOfDone: Item[];
  /** The description's Start Criteria with their results; absent from a record the board cannot evaluate. */
  start_criteria?: StartCriterion[];
}

export type TaskField = keyof TaskRecord;
export interface TaskDiff {
  fields: TaskField[];
  base: Partial<TaskRecord>;
  changes: Partial<TaskRecord>;
}

const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** The fields whose draft value differs, with exactly the matching values from the record that was opened. */
export function changedFields(base: TaskRecord, draft: TaskRecord): TaskDiff {
  const fields = (Object.keys(base) as TaskField[]).filter((field) => !equal(base[field], draft[field]));
  return {
    fields,
    base: Object.fromEntries(fields.map((field) => [field, base[field]])),
    changes: Object.fromEntries(fields.map((field) => [field, draft[field]])),
  };
}

/** Acceptance criteria newly checked in this draft; each needs evidence in the edit's recorded comment. */
export function newlyChecked(base: TaskRecord, draft: TaskRecord): number[] {
  const was = new Map(base.acceptanceCriteria.map((item) => [item.n, item.checked]));
  return draft.acceptanceCriteria.filter((item) => item.checked && !was.get(item.n)).map((item) => item.n);
}

export type SaveResult =
  | { ok: true; changed: TaskField[]; record: TaskRecord }
  | { ok: false; missingEvidence: number[]; record: TaskRecord }
  | { ok: false; reason: string; skill: string; fields: TaskField[]; record: TaskRecord };

/** Save one task diff. Validation happens before the sole request, and a refusal returns the caller's draft intact. */
export async function saveTask(
  task: string,
  base: TaskRecord,
  draft: TaskRecord,
  evidence: Record<number, string>,
  fetcher: typeof apiFetch = apiFetch,
): Promise<SaveResult> {
  const diff = changedFields(base, draft);
  const checked = newlyChecked(base, draft);
  const missingEvidence = checked.filter((n) => !evidence[n]?.trim());
  if (missingEvidence.length) return { ok: false, missingEvidence, record: draft };
  if (!diff.fields.length) return { ok: true, changed: [], record: draft };
  const comment = checked.map((n) => `AC #${n}: ${evidence[n].trim()}`).join("\n");
  let response: Response;
  try {
    response = await fetcher("/api/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task, base: diff.base, changes: diff.changes, comment }),
    });
  } catch {
    return { ok: false, reason: "The task writer could not be reached.", skill: "", fields: diff.fields, record: draft };
  }
  const body = await response.json().catch(() => ({})) as { changed?: TaskField[]; error?: string; skill?: string; stale?: TaskField[] };
  if (response.ok) return { ok: true, changed: body.changed ?? diff.fields, record: draft };
  return {
    ok: false,
    reason: body.error ?? `The task writer answered ${response.status}.`,
    skill: body.skill ?? "",
    fields: body.stale?.length ? body.stale : diff.fields,
    record: draft,
  };
}

export type EditAction = "save" | "discard" | "cancel";

export const discardMessage = (changes: number): string => `Discard ${changes} change${changes === 1 ? "" : "s"}?`;

/** The edit form's document-level shortcuts. */
export function editKey(key: string, ctrl: boolean, meta: boolean, dirty: boolean): EditAction | null {
  if (key === "Escape") return dirty ? "discard" : "cancel";
  if (key === "Enter" && (ctrl || meta)) return "save";
  return null;
}

export const PRIORITIES = ["High", "Medium", "Low"];

/** The task's record from the server, or null when the board cannot read it or the request failed. */
export async function fetchRecord(id: string, fetcher: typeof apiFetch = apiFetch): Promise<TaskRecord | null> {
  try {
    const response = await fetcher(`/api/task/${encodeURIComponent(id)}`);
    if (!response.ok) return null;
    const body: { record?: TaskRecord } | null = await response.json().catch(() => null);
    return body?.record ?? null;
  } catch {
    return null;
  }
}

export interface MenuState { open: boolean; on: number }
export interface MenuStep {
  state: MenuState;
  /** The index of the item chosen, when the key chose one. */
  pick: number | null;
  /** Whether the menu used the key, so the page must not: Escape closes only the menu, not the task view. */
  handled: boolean;
}

/** What a key does to the Move to menu whose items are enabled as `enabled` says. */
export function menuKey(state: MenuState, key: string, enabled: boolean[]): MenuStep {
  const n = enabled.length;
  const shut: MenuState = { open: false, on: -1 };
  if (!state.open) {
    if (!n || (key !== "ArrowDown" && key !== "ArrowUp")) return { state, pick: null, handled: false };
    return { state: { open: true, on: key === "ArrowUp" ? n - 1 : 0 }, pick: null, handled: true };
  }
  switch (key) {
    case "Escape": return { state: shut, pick: null, handled: true };
    case "ArrowDown": return { state: { open: true, on: (state.on + 1) % n }, pick: null, handled: true };
    case "ArrowUp": return { state: { open: true, on: (state.on + n - 1) % n }, pick: null, handled: true };
    case "Enter":
    case " ": return enabled[state.on] ? { state: shut, pick: state.on, handled: true } : { state, pick: null, handled: true };
    case "Tab": return { state: shut, pick: null, handled: false };
    default: return { state, pick: null, handled: false };
  }
}

/** The text Copy puts on the clipboard: the task's id and its title. */
export const copyText = (task: { id: string }, title: string): string => `${task.id} ${title}`;

/** Write `text` to the clipboard; false when the browser refuses. A page served over plain http has no async clipboard, so a selection copy stands in. */
export async function copyToClipboard(text: string, clipboard: Pick<Clipboard, "writeText"> | undefined = globalThis.navigator?.clipboard): Promise<boolean> {
  try {
    if (clipboard) {
      await clipboard.writeText(text);
      return true;
    }
  } catch {
    // refused: fall back to a selection copy
  }
  if (typeof document === "undefined") return false;
  const box = document.createElement("textarea");
  box.value = text;
  box.style.cssText = "position:fixed;opacity:0";
  document.body.append(box);
  box.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    box.remove();
  }
}

/** A press on the dimmed scrim, not on the dialog above it, dismisses the modal. */
export const onScrim = (target: unknown, scrim: unknown): boolean => target === scrim;

/** Escape closes the modal, except in the edit form, whose own shortcuts own it. */
export const closesOnKey = (key: string, editing: boolean): boolean => key === "Escape" && !editing;

export interface Block { kind: "p" | "h" | "pre" | "moved"; text: string }

/** What the description's `start_criteria` block gives way to once the rail draws the criteria. */
export const CRITERIA_POINTER = "Start Criteria are drawn in the side panel, each with its result →";

/** A task description's Markdown as the blocks the read view draws: paragraphs, `##` headings and fenced code; with `drawn`, the `start_criteria` block is a pointer to the rail. */
export function markdown(text: string, drawn = false): Block[] {
  const blocks: Block[] = [];
  let lines: string[] = [];
  let fence = false;
  const flush = (kind: Block["kind"]) => {
    if (lines.length || kind === "pre") blocks.push({ kind, text: lines.join("\n") });
    lines = [];
  };
  for (const line of text.split("\n")) {
    if (line.startsWith("```")) {
      flush(fence ? "pre" : "p");
      if (drawn && fence && /^start_criteria:/m.test(blocks[blocks.length - 1].text)) blocks[blocks.length - 1] = { kind: "moved", text: CRITERIA_POINTER };
      fence = !fence;
    } else if (fence) lines.push(line);
    else if (line.startsWith("## ")) {
      flush("p");
      blocks.push({ kind: "h", text: line.slice(3) });
    } else if (line.trim()) lines.push(line);
    else flush("p");
  }
  flush(fence ? "pre" : "p");
  return blocks;
}

/** How many of the tasks a task holds the rail lists before it counts the rest. */
export const HOLDS_SHOWN = 6;

/** One task the rail's Dependencies section names: its id, its title and lane, or null for both when it is not on the board. */
export interface DepRow { id: string; title: string | null; lane: string | null }

/** What a task depends on, and the tasks that depend on it (the first six, with how many more follow). */
export function dependencyRows(tasks: KanbanTask[], task: KanbanTask): { dependsOn: DepRow[]; holds: DepRow[]; more: number } {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const row = (id: string): DepRow => ({ id, title: byId.get(id)?.title ?? null, lane: byId.get(id)?.lane ?? null });
  const held = tasks.filter((t) => t.dependencies.includes(task.id));
  return { dependsOn: task.dependencies.map(row), holds: held.slice(0, HOLDS_SHOWN).map((t) => row(t.id)), more: Math.max(0, held.length - HOLDS_SHOWN) };
}

/** How many criteria are met. */
export const metCount = (criteria: StartCriterion[]): number => criteria.filter((c) => c.status === "met").length;

/** A `time()` criterion waits for a moment, not a measurement. */
const waitsForTime = (c: StartCriterion): boolean => c.expr.replace(/\s/g, "") === "time()" && c.cmp === "at_least" && typeof c.want === "number";

/** `threshold · last value · checked <age>` for a criterion, or `opens <date MST>` for a `time()` one; parts it lacks are left out. */
export function criterionDetail(c: StartCriterion, now: number): string {
  const checked = c.checked ? Date.parse(c.checked) / 1000 : NaN;
  const threshold = waitsForTime(c) ? `opens ${fmtAt(c.want as number)} MST` : c.cmp ? `${c.cmp.replace("_", " ")} ${String(c.want)}` : "";
  const last = c.status === "error" || waitsForTime(c) || c.observed == null ? "" : `last ${String(c.observed)}`;
  return [threshold, last, Number.isNaN(checked) ? "" : `checked ${ago(now - checked)} ago`].filter(Boolean).join(" · ");
}
