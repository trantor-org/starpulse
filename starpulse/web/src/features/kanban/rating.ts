// Rating a task from the task view: the one request and how the control reads a rating.
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";
import type { Rated, Rating } from "../../api";

export type Verdict = "pass" | "fail" | "cleared";

/** The longest reason the rating API takes. */
export const REASON_MAX = 120;

/** Write one rating change as the operator; the refused or unreachable write comes back as null, never a throw. */
export async function postRating(task: string, verdict: Verdict, reason = "", fetcher: typeof apiFetch = apiFetch): Promise<Rated | null> {
  try {
    const response = await fetcher("/api/rating", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ task, verdict, ...(reason && { reason }), actor: PAGE_ACTOR }) });
    return response.ok ? await response.json() as Rated : null;
  } catch {
    return null;
  }
}

/** The verdict a rating stands for: a cleared rating, like none, stands for no verdict. */
export const verdictOf = (rating: Rating | undefined): "pass" | "fail" | null =>
  rating?.verdict === "pass" || rating?.verdict === "fail" ? rating.verdict : null;

const plural = (n: number) => `${n} ${n === 1 ? "change" : "changes"}`;

/** `Passed by operator · 4m ago · 2 changes`; the snapshot keeps the latest change and the count, so that is the history. */
export function ratingMeta(rating: Rating, verdict: "pass" | "fail", span: string): string {
  return `${verdict === "pass" ? "Passed" : "Failed"} by ${rating.actor || "anonymous"} · ${span} · ${plural(rating.changes)}`;
}

export const ratingHistory = (rating: Rating, at: string): string => `${plural(rating.changes)}; the latest, ${rating.verdict === "pass" ? "pass" : rating.verdict}, at ${at}`;
