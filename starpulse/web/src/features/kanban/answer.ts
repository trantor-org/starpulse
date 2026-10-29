// Answering a Needs attention question from the task view: the one request.
import { apiFetch } from "../../api/apiFetch";
import type { Answered } from "../../api";

/** The answer recorded, or why the server refused it; an unreachable server reads as a refusal, never a throw. */
export type AnswerResult = { answered: Answered } | { refused: string };

/** Send the operator's answer. It names no actor: the server takes a same-origin request from this page as the operator's. */
export async function postAnswer(task: string, answer: string, fetcher: typeof apiFetch = apiFetch): Promise<AnswerResult> {
  try {
    const response = await fetcher("/api/answer", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ task, answer }) });
    if (response.ok) return { answered: await response.json() as Answered };
    const body = await response.json().catch(() => ({})) as { error?: string };
    return { refused: body.error ?? `refused (${response.status})` };
  } catch {
    return { refused: "the server was unreachable" };
  }
}
