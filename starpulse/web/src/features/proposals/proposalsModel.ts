// The Proposals view's model: which tasks are proposals, how a proposal's description reads, and the two decisions the operator
// makes on one. Promote and Drop are the board machine's PROMOTE and DROP events: a move to the Ready role and to the final role.
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";
import type { Roles } from "../../api";
import type { KanbanTask } from "../kanban/kanbanModel";
import { postMove, type Reply } from "../kanban/move";

/** Every task whose State is the lifecycle's Proposed role, the newest first; empty when the lifecycle declares none. */
export function proposedOf(cards: KanbanTask[], roles: Roles): KanbanTask[] {
  const proposed = roles.proposed;
  if (!proposed) return [];
  return cards.filter((c) => c.lane === proposed).sort((a, b) => (b.created ?? 0) - (a.created ?? 0));
}

const sectionOf = (text: string, heading: string): string => {
  const found = text.split(/^## /m).find((part) => part.startsWith(`${heading}\n`));
  return found ? found.slice(heading.length).trim() : "";
};

/** The why (the Why section, else the text before the first heading) and the Duplicate Resolution section of a task's description. */
export function sectionsOf(description: string): { why: string; duplicate: string } {
  const why = sectionOf(description, "Why") || description.split(/^## /m)[0].trim();
  return { why, duplicate: sectionOf(description, "Duplicate Resolution") };
}

/** Set the profile when it changed, then move the task to Ready. A refused edit moves nothing. */
export async function promoteProposal(
  task: string, profile: string, current: string, roles: Roles, fetcher: typeof apiFetch = apiFetch,
): Promise<Reply> {
  if (profile !== current) {
    const failed = await editProfile(task, profile, current, fetcher);
    if (failed) return failed;
  }
  return postMove(task, roles.ready ?? "ready", fetcher);
}

/** Archive a proposal: a move to the lifecycle's final State. */
export const dropProposal = (task: string, roles: Roles, fetcher: typeof apiFetch = apiFetch): Promise<Reply> =>
  postMove(task, roles.final ?? "archived", fetcher);

async function editProfile(task: string, profile: string, current: string, fetcher: typeof apiFetch): Promise<Reply | null> {
  let response: Response;
  try {
    response = await fetcher("/api/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task, base: { profile: current }, changes: { profile }, actor: PAGE_ACTOR }),
    });
  } catch {
    return { ok: false, reason: "the edit did not reach the server", skill: "" };
  }
  if (response.ok) return null;
  const body: { error?: string } | null = await response.json().catch(() => null);
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}`, skill: "" };
}
