// Freezing a task from the task view: the one request the task actor acts on, whose snapshot then draws the freeze.
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";

export type FreezeResult = { ok: true } | { ok: false; reason: string };

/** Ask for `task` to be frozen for a reason, or unfrozen with `null`; a refusal comes back as a value, never a throw. */
export async function postFreeze(task: string, reason: string | null, fetcher: typeof apiFetch = apiFetch): Promise<FreezeResult> {
  const change = reason === null ? { unfreeze: true } : { freeze: reason };
  let response: Response;
  try {
    response = await fetcher(`/api/tasks/${encodeURIComponent(task)}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...change, actor: PAGE_ACTOR }) });
  } catch {
    return { ok: false, reason: "The task writer could not be reached; the freeze did not change." };
  }
  if (response.ok) return { ok: true };
  const body = await response.json().catch(() => ({})) as { error?: string };
  return { ok: false, reason: body.error ?? `The task writer answered ${response.status}; the freeze did not change.` };
}
