// Creating a task from the Kanban toolbar: the form's draft, the one request it sends, what the form holds after it, and its keys.
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";

/** The New task form as typed: labels and dependencies stay comma-separated text until the create, so a comma can be typed. */
export interface NewTaskDraft {
  title: string;
  outcome: string;
  why: string;
  currentState: string;
  /** One item per line. */
  scope: string;
  outOfScope: string;
  stopConditions: string;
  reach: string;
  data: string;
  undo: string;
  detect: string;
  blastNote: string;
  rollback: string;
  priority: string;
  impact: string;
  urgency: string;
  labels: string;
  milestone: string;
  assignee: string;
  dependencies: string;
  acceptanceCriteria: string[];
}

export const EMPTY_DRAFT: NewTaskDraft = {
  title: "", outcome: "", why: "", currentState: "", scope: "", outOfScope: "", stopConditions: "", reach: "", data: "", undo: "", detect: "", blastNote: "", rollback: "", priority: "", impact: "", urgency: "", labels: "", milestone: "", assignee: "", dependencies: "", acceptanceCriteria: [],
};

export type CreateResult = { ok: true; task: string } | { ok: false; reason: string; skill: string };

const split = (text: string, separator: string) => text.split(separator).map((v) => v.trim()).filter(Boolean);
const list = (text: string) => split(text, ",");

/** The typed brief the create takes in place of a description: one key per field, a blank one left out so the board's refusal names it. */
function briefBody(draft: NewTaskDraft): Record<string, unknown> {
  const brief: Record<string, unknown> = {};
  for (const [key, text] of [["outcome", draft.outcome], ["why", draft.why], ["current_state", draft.currentState], ["rollback", draft.rollback]] as const) {
    if (text.trim()) brief[key] = text.trim();
  }
  for (const [key, text] of [["scope", draft.scope], ["out_of_scope", draft.outOfScope], ["stop_conditions", draft.stopConditions]] as const) {
    const items = split(text, "\n");
    if (items.length) brief[key] = items;
  }
  const radius: Record<string, unknown> = {};
  for (const axis of ["reach", "data", "undo", "detect"] as const) if (draft[axis]) radius[axis] = Number(draft[axis]);
  if (draft.blastNote.trim()) radius.note = draft.blastNote.trim();
  if (Object.keys(radius).length) brief.blast_radius = radius;
  return brief;
}

/** The draft field a refusal names, from its `invalid request: brief.<path>: why` text; null when it names none. */
export function refusedField(reason: string | null): keyof NewTaskDraft | null {
  const path = /^invalid request: brief\.(?:blast_radius\.)?([a-z_]+)/.exec(reason ?? "");
  if (!path || path[1] === "blast_radius") return null;
  const key = path[1] === "note" ? "blast_note" : path[1];
  return key.replace(/_(\w)/g, (_, c: string) => c.toUpperCase()) as keyof NewTaskDraft;
}

/** `PUT /api/tasks`'s body: the trimmed title, the page's actor, the typed brief and every other field the draft filled, lists split and blank criteria dropped. */
export function createBody(draft: NewTaskDraft): Record<string, unknown> {
  const body: Record<string, unknown> = { brief: briefBody(draft), title: draft.title.trim(), actor: PAGE_ACTOR };
  for (const field of ["priority", "impact", "urgency", "milestone", "assignee"] as const) {
    if (draft[field].trim()) body[field] = draft[field].trim();
  }
  for (const [field, values] of [["labels", list(draft.labels)], ["dependencies", list(draft.dependencies)],
    ["acceptanceCriteria", draft.acceptanceCriteria.map((v) => v.trim()).filter(Boolean)]] as const) {
    if (values.length) body[field] = values;
  }
  return body;
}

/** Ask the board to create the drafted task in its starting lane; a refusal comes back as a value, never a throw. */
export async function postCreate(draft: NewTaskDraft, fetcher: typeof apiFetch = apiFetch): Promise<CreateResult> {
  let response: Response;
  try {
    response = await fetcher("/api/tasks", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(createBody(draft)) });
  } catch {
    return { ok: false, reason: "The task writer could not be reached; the task was not created.", skill: "" };
  }
  const body = await response.json().catch(() => ({})) as { task?: string; error?: string; skill?: string };
  if (response.ok && body.task) return { ok: true, task: body.task };
  return { ok: false, reason: body.error ?? `The task writer answered ${response.status}; the task was not created.`, skill: body.skill ?? "" };
}

/** What the form holds once `result` came back for `draft`: a created task empties it, a refused one keeps all of it and says why. */
export const createOutcome = (draft: NewTaskDraft, result: CreateResult): { draft: NewTaskDraft; refused: string | null; created: string | null } =>
  result.ok ? { draft: EMPTY_DRAFT, refused: null, created: result.task } : { draft, refused: result.reason, created: null };

/** The form's keys, as the task view's editor has them: Ctrl or Cmd+Enter creates, Escape cancels; none acts while a create runs. */
export const newTaskKey = (key: string, modified: boolean, busy: boolean): "submit" | "cancel" | null =>
  busy ? null : key === "Enter" && modified ? "submit" : key === "Escape" ? "cancel" : null;
