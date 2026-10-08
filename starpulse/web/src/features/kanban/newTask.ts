// Creating a task from the Kanban toolbar: the form's draft, the one request it sends, what the form holds after it, and its keys.
import { apiFetch } from "../../api/apiFetch";

/** The New task form as typed: labels and dependencies stay comma-separated text until the create, so a comma can be typed. */
export interface NewTaskDraft {
  title: string;
  description: string;
  priority: string;
  labels: string;
  milestone: string;
  assignee: string;
  dependencies: string;
  acceptanceCriteria: string[];
}

export const EMPTY_DRAFT: NewTaskDraft = {
  title: "", description: "", priority: "", labels: "", milestone: "", assignee: "", dependencies: "", acceptanceCriteria: [],
};

export type CreateResult = { ok: true; task: string } | { ok: false; reason: string; skill: string };

const list = (text: string) => text.split(",").map((v) => v.trim()).filter(Boolean);

/** `POST /api/tasks`'s body: the trimmed title and every other field the draft filled, lists split and blank criteria dropped. */
export function createBody(draft: NewTaskDraft): Record<string, string | string[]> {
  const body: Record<string, string | string[]> = { title: draft.title.trim() };
  for (const field of ["description", "priority", "milestone", "assignee"] as const) {
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
    response = await fetcher("/api/tasks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(createBody(draft)) });
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
