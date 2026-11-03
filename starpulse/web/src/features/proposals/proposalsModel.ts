// The Proposals view's model: which tasks are proposals, how a proposal's description reads, and the two decisions the operator
// makes on one. Promote and Drop are the board machine's PROMOTE and DROP events: a move to the Ready role and to the final role.
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";
import type { Roles } from "../../api";
import type { KanbanTask } from "../kanban/kanbanModel";
import { postMove, type Reply } from "../kanban/move";
import type { Harnesses } from "../kanban/start";
import type { TaskComment } from "../kanban/taskViewModel";

/** The label the hourly triage puts on a Proposed task it pre-approved, and the prefix of the comment that records why (TASK-11161). */
export const PREAPPROVED_LABEL = "triage-preapproved";
const VERDICT_PREFIX = "triage verdict: pre-approved:";

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

/** Set the profile when it changed, then move the task to Ready, or to Waiting when a dependency is open. A refused edit moves nothing. */
export async function promoteProposal(
  task: string, profile: string, current: string, roles: Roles, fetcher: typeof apiFetch = apiFetch, openDeps = 0,
): Promise<Reply> {
  if (profile !== current) {
    const failed = await editProfile(task, profile, current, fetcher);
    if (failed) return failed;
  }
  const target = openDeps > 0 ? (roles.waiting ?? "waiting") : (roles.ready ?? "ready");
  return postMove(task, target, fetcher);
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

/** Whether the triage pre-approved this proposal; a proposal without the label is Unapproved. */
export const isPreapproved = (card: KanbanTask): boolean => card.labels.includes(PREAPPROVED_LABEL);

/** The reason of the newest pre-approved verdict comment; empty when no comment records one. */
export function verdictOf(comments: TaskComment[] | undefined): string {
  const verdict = [...(comments ?? [])].reverse().find((c) => c.text.startsWith(VERDICT_PREFIX));
  return verdict ? verdict.text.slice(VERDICT_PREFIX.length).trim() : "";
}

const labelValue = (labels: string[], prefix: string): string => labels.find((l) => l.startsWith(prefix))?.slice(prefix.length) ?? "";
export const kindOf = (labels: string[]): string => labelValue(labels, "kind-");
export const sizeOf = (labels: string[]): string => labelValue(labels, "size-");

/** The model a profile (`@agent-standard-high`) runs on the first harness that has its tier; empty when none does. */
export function modelOf(profile: string, harnesses: Harnesses): string {
  const [, tier, effort = ""] = /^@agent-([a-z]+)(?:-([a-z]+))?$/.exec(profile) ?? [];
  const found = harnesses.harnesses.map((h) => h.tiers[tier]).find(Boolean);
  return found ? (effort && found.models?.[effort]) || found.model : "";
}

/** Whether every word of `query` appears in the proposal's id, title or description (the loaded detail's when it has one), ignoring case. */
export function matchesQuery(card: KanbanTask, query: string, description = card.description): boolean {
  const haystack = [card.id, card.title, description ?? ""].join(" ").toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
}

export type GroupBy = "none" | "milestone" | "priority" | "kind";
export type SortBy = "newest" | "oldest" | "priority";
export interface Group { label: string; cards: KanbanTask[] }

const PRIORITIES = ["high", "medium", "low"];
const rank = (priority: string | undefined): number => {
  const at = PRIORITIES.indexOf(priority ?? "");
  return at < 0 ? PRIORITIES.length : at;
};

/** `cards` ordered by `sort` and split by `by` into labelled groups, an ungrouped value last. `priority` comes from the loaded detail. */
export function groupsOf(cards: KanbanTask[], by: GroupBy, sort: SortBy, details: Record<string, { priority?: string }>): Group[] {
  const order = (a: KanbanTask, b: KanbanTask): number => {
    if (sort === "oldest") return (a.created ?? 0) - (b.created ?? 0);
    if (sort === "priority") return rank(details[a.id]?.priority) - rank(details[b.id]?.priority) || (b.created ?? 0) - (a.created ?? 0);
    return (b.created ?? 0) - (a.created ?? 0);
  };
  const sorted = [...cards].sort(order);
  if (by === "none") return sorted.length ? [{ label: "", cards: sorted }] : [];
  const none = { milestone: "No milestone", priority: "No priority", kind: "No kind" }[by];
  const keyOf = (c: KanbanTask): string => (by === "milestone" ? c.milestone : by === "priority" ? details[c.id]?.priority ?? "" : kindOf(c.labels)) || none;
  const labels = [...new Set(sorted.map(keyOf))];
  const place = (label: string): number => (label === none ? 1 : 0);
  const byName = (a: string, b: string): number => (by === "priority" ? rank(a) - rank(b) : a.localeCompare(b));
  labels.sort((a, b) => place(a) - place(b) || byName(a, b));
  return labels.map((label) => ({ label, cards: sorted.filter((c) => keyOf(c) === label) }));
}
