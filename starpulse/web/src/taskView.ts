// The task view's model: the full record GET /api/task/<id> returns, and the Move to menu's keyboard.
import { apiFetch } from "./demo";

export interface Item { n: number; text: string; checked: boolean }

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

export interface Block { kind: "p" | "h" | "pre"; text: string }

/** A task description's Markdown as the blocks the read view draws: paragraphs, `##` headings and fenced code. */
export function markdown(text: string): Block[] {
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
