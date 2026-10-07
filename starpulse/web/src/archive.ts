// Archiving a task from the task view: what the confirm warns about, the one request, and the cards an archive removes.
import { apiFetch } from "./demo";
import type { KanbanTask } from "./kanban";
import type { Pull } from "./api";

/** Work that outlives the archive: the task's open pull request and the agent session still working it. */
export interface ArchiveWarnings {
  pull: Pull | null;
  session: KanbanTask["live"];
}
export type ArchiveResult = { ok: true } | { ok: false; reason: string; skill: string };
export type ArchiveAction = "cancel" | "confirm";

export const archiveWarnings = (task: KanbanTask): ArchiveWarnings => ({
  pull: task.prs.find((pr) => !pr.merged) ?? null,
  session: task.lane === "in_progress" ? task.live : null,
});

/** Archive one task, recording `reason` as its comment when it is not empty; a refusal comes back as a value, never a throw. */
export async function postArchive(task: string, reason: string, fetcher: typeof apiFetch = apiFetch): Promise<ArchiveResult> {
  let response: Response;
  try {
    response = await fetcher("/api/archive", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ task, reason }) });
  } catch {
    return { ok: false, reason: "The task writer could not be reached; the task was not archived.", skill: "" };
  }
  if (response.ok) return { ok: true };
  const body = await response.json().catch(() => ({})) as { error?: string; skill?: string };
  return { ok: false, reason: body.error ?? `The task writer answered ${response.status}; the task was not archived.`, skill: body.skill ?? "" };
}

/** The confirm's document-level keys; none acts while the archive runs. */
export function archiveKey(key: string, ctrl: boolean, meta: boolean, busy: boolean): ArchiveAction | null {
  if (busy) return null;
  if (key === "Escape") return "cancel";
  if (key === "Enter" && (ctrl || meta)) return "confirm";
  return null;
}

/** The cards without the tasks archived here, so the card and its column's count drop before the next snapshot says so. */
export const withoutArchived = (tasks: KanbanTask[], gone: ReadonlySet<string>): KanbanTask[] =>
  gone.size ? tasks.filter((t) => !gone.has(t.id)) : tasks;

/** The dialog renders beside the task's Modal, which is keyed by the bare id; React reconciles keyed siblings together, so a shared key duplicates the Modal's node on every render. */
export const archiveDialogKey = (id: string) => `archive-${id}`;
