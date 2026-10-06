// Creating a task from the Kanban toolbar: the one request, what the field holds after it, and its keys.
import { apiFetch } from "./demo";

export type CreateResult = { ok: true; task: string } | { ok: false; reason: string; skill: string };

/** Ask the board to create a task titled `title` in its first lane; a refusal comes back as a value, never a throw. */
export async function postCreate(title: string, fetcher: typeof apiFetch = apiFetch): Promise<CreateResult> {
  let response: Response;
  try {
    response = await fetcher("/api/tasks", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ title }) });
  } catch {
    return { ok: false, reason: "The task writer could not be reached; the task was not created.", skill: "" };
  }
  const body = await response.json().catch(() => ({})) as { task?: string; error?: string; skill?: string };
  if (response.ok && body.task) return { ok: true, task: body.task };
  return { ok: false, reason: body.error ?? `The task writer answered ${response.status}; the task was not created.`, skill: body.skill ?? "" };
}

/** What the field holds once `result` came back for `title`: a created task empties it, a refused one keeps the title and says why. */
export const createOutcome = (title: string, result: CreateResult): { title: string; refused: string | null; created: string | null } =>
  result.ok ? { title: "", refused: null, created: result.task } : { title, refused: result.reason, created: null };

/** The field's keys; none acts while a create runs. */
export const newTaskKey = (key: string, busy: boolean): "submit" | "cancel" | null =>
  busy ? null : key === "Enter" ? "submit" : key === "Escape" ? "cancel" : null;
