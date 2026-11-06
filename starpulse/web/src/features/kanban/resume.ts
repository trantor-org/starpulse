// Resuming a parked task's session from its card: the lanes a session parks from, the request, and the link the resume left on the task.
import { apiFetch } from "../../api/apiFetch";
import type { Roles } from "../../api";
import type { TaskComment } from "./taskViewModel";

export type ResumeReply = { ok: true; url: string } | { ok: false; reason: string };

/** Whether a task in `lane` can be resumed: a session parks from review, waiting and needs attention. */
export const resumable = (lane: string, roles: Roles): boolean => [roles.review, roles.waiting, roles.attention].some((role) => !!role && role === lane);

/** POST /api/resume: the parked session is recreated with Remote Control and `text` as its first message; a refused or unreachable resume reads as a reason. */
export async function postResume(task: string, text: string, fetcher: typeof apiFetch = apiFetch): Promise<ResumeReply> {
  let response: Response;
  try {
    response = await fetcher("/api/resume", { method: "POST", body: JSON.stringify(text.trim() ? { task, text: text.trim() } : { task }) });
  } catch {
    return { ok: false, reason: "the resume did not reach the server" };
  }
  const body: { url?: string; error?: string } | null = await response.json().catch(() => null);
  if (response.ok && body?.url) return { ok: true, url: body.url };
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}` };
}

const RESUMED = /^Resumed in (https:\/\/\S+)$/;

/** The session link the latest resume recorded on the task, or null when it was never resumed. */
export const resumedLink = (comments: readonly TaskComment[]): string | null => {
  const link = [...comments].reverse().map((comment) => RESUMED.exec(comment.text.trim())?.[1]).find(Boolean);
  return link ?? null;
};
