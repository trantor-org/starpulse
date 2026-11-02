// The task view's model: the full record GET /api/task/<id> returns, and the Move to menu's keyboard.
import { ago, fmtAt } from "../../shared/clock";
import { apiFetch, PAGE_ACTOR } from "../../api/apiFetch";
import type { KanbanTask } from "./kanbanModel";

export interface Item { n: number; text: string; checked: boolean }

/** One Start Criterion of a task as the board reader evaluates it: `status` is `met`, `unmet`, `error` or `not evaluated`, and `checked` an ISO time. */
export interface StartCriterion {
  id: string;
  kind: string;
  expr: string;
  cmp: string | null;
  want: unknown;
  status: string;
  observed: unknown;
  error: string | null;
  checked: string | null;
}

/** Every field of a task the view draws that the snapshot's small entry does not carry. */
export interface TaskRecord {
  title: string;
  profile: string;
  priority: string;
  labels: string[];
  milestone: string;
  /** The files of the docs the task links, as the board writes them. Read-only: an edit never carries it. */
  documentation?: string[];
  /** The task's type (`story`); read-only, and absent from a record the board does not type. */
  type?: string;
  dependencies: string[];
  description: string;
  plan: string;
  notes: string;
  acceptanceCriteria: Item[];
  definitionOfDone: Item[];
  /** The description's Start Criteria with their results; absent from a record the board cannot evaluate. */
  start_criteria?: StartCriterion[];
  /** The link of the claiming session's latest Session Link line, empty when the board records none. Read-only: an edit never carries it. */
  session?: string;
  /** The session that filed the task (`created_by`), empty when the board records none. Read-only: an edit never carries it. */
  createdBy?: string;
  /** The task's comments, oldest first. Read-only: a comment is posted through `postComment`, never an edit's changes. */
  comments?: TaskComment[];
  /** The lane as the board names it (`Done`). Read-only: a task moves through its moves, never an edit. */
  status?: string;
  /** The links the task cites, its pull requests among them. Read-only: an edit never carries it. */
  references?: string[];
}

export interface TaskComment { created: string; text: string; author?: string }

export type TaskField = Exclude<keyof TaskRecord, "session" | "createdBy" | "comments" | "documentation" | "status" | "references">;
export interface TaskDiff {
  fields: TaskField[];
  base: Partial<TaskRecord>;
  changes: Partial<TaskRecord>;
}

const equal = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** The fields whose draft value differs, with exactly the matching values from the record that was opened. */
export function changedFields(base: TaskRecord, draft: TaskRecord): TaskDiff {
  const fields = (Object.keys(base) as (keyof TaskRecord)[]).filter((field): field is TaskField => field !== "session" && !equal(base[field], draft[field]));
  return {
    fields,
    base: Object.fromEntries(fields.map((field) => [field, base[field]])),
    changes: Object.fromEntries(fields.map((field) => [field, draft[field]])),
  };
}

/** Acceptance criteria newly checked in this draft; each needs evidence in the edit's recorded comment. */
export function newlyChecked(base: TaskRecord, draft: TaskRecord): number[] {
  const was = new Map(base.acceptanceCriteria.map((item) => [item.n, item.checked]));
  return draft.acceptanceCriteria.filter((item) => item.checked && !was.get(item.n)).map((item) => item.n);
}

export type SaveResult =
  | { ok: true; changed: TaskField[]; record: TaskRecord }
  | { ok: false; missingEvidence: number[]; record: TaskRecord }
  | { ok: false; reason: string; skill: string; fields: TaskField[]; record: TaskRecord };

const CHECKLISTS: TaskField[] = ["acceptanceCriteria", "definitionOfDone"];

/** A checklist item added in the editor carries n 0 until the board numbers it; the writer takes an item without a number as new. */
const withoutNew = (changes: Partial<TaskRecord>): Partial<TaskRecord> => Object.fromEntries(Object.entries(changes).map(([field, value]) =>
  [field, CHECKLISTS.includes(field as TaskField) ? (value as Item[]).map(({ n, ...rest }) => n ? { n, ...rest } : rest) : value]));

/** One row of Activity or Comments: who wrote it, when (epoch seconds), its Markdown body, and for a checkpoint the criterion it verified and the command output it recorded. */
export interface ActivityEvent { key: string; at: number; kind: "checkpoint" | "system" | "comment"; who: string; body: string; ac?: number; detail?: string }

const VERIFIED = /^Verified AC #(\d+):\s*/;
/** `checkpoint-ac --run` evidence, passed or not, is its command line, a blank line, then the output tail in a fence. */
const OUTPUT_FENCE = /^```\w*\n?|\n?```$/g;
const fold = (text: string) => {
  const cut = text.indexOf("\n\n```");
  const detail = cut < 0 ? "" : text.slice(cut + 2).trim().replace(OUTPUT_FENCE, "").trim();
  return { body: cut < 0 ? text : text.slice(0, cut), ...(detail && { detail }) };
};
const SESSION_LINK = /^\*\*Session Link:\*\* (\S+)/;
/** The harness logs every tool call a session makes, and a checkpoint step only echoes the comment that carries its evidence. */
const QUIET_MACHINE = "harness";
const QUIET_EVENT = "AC_CHECKPOINTED";

/** A comment as a row: `task checkpoint-ac` evidence, a session's claim and the board's own notes are activity; the rest is conversation. */
function commentRow(c: TaskComment, i: number): ActivityEvent {
  const row = { key: `c${i}`, at: Date.parse(c.created.replace(" ", "T")) / 1000 || 0, who: c.author ?? "agent", body: c.text };
  const verified = VERIFIED.exec(c.text);
  if (verified) return { ...row, kind: "checkpoint", ac: Number(verified[1]), ...fold(c.text.slice(verified[0].length)) };
  const link = SESSION_LINK.exec(c.text)?.[1];
  if (link) return { ...row, kind: "system", body: `Claimed by session [\`${link.split("/").pop()!.replace(/^session_/, "").slice(0, 8)}\`](${link})` };
  if (row.who.startsWith("starpulse/")) return { ...row, kind: "system", who: "starpulse" };
  return { ...row, kind: "comment", ...fold(c.text) };
}

/** One machine's lifecycle steps under Activity, oldest first, with the state it stands in and when it last moved. */
export interface MachineGroup { machine: string; state: string; at: number; steps: ActivityEvent[] }

/** D4: Activity is the read-only record, oldest first (checkpoints, the claim), with each machine's lifecycle steps in a group of its own; Comments is everything people wrote. */
export function taskActivity(task: KanbanTask, comments: TaskComment[]): { activity: ActivityEvent[]; machines: MachineGroup[]; comments: ActivityEvent[] } {
  const rows = comments.map(commentRow);
  const groups = task.machines.filter((m) => m.machine !== QUIET_MACHINE).map((m): MachineGroup => ({
    machine: m.machine, state: m.state, at: m.at,
    steps: m.trail.filter((s) => s.event !== QUIET_EVENT).map((s, i): ActivityEvent => (
      { key: `${m.machine}${i}`, at: s.at, kind: "system", who: m.machine, body: `\`${s.event}\` → ${s.state.replace(/_/g, " ")}` })),
  }));
  return {
    activity: rows.filter((r) => r.kind !== "comment").sort((a, b) => a.at - b.at),
    machines: groups.filter((g) => g.steps.length > 0).sort((a, b) => a.steps[0].at - b.steps[0].at),
    comments: rows.filter((r) => r.kind === "comment"),
  };
}

/** Post a comment through the edit endpoint. A comment writes no field, so the request names the title as it stands and changes nothing. */
export async function postComment(task: string, base: TaskRecord, text: string, fetcher: typeof apiFetch = apiFetch): Promise<boolean> {
  try {
    const response = await fetcher("/api/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task, base: { title: base.title }, changes: { title: base.title }, comment: text.trim(), actor: PAGE_ACTOR }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/** Save one task diff. Validation happens before the sole request, and a refusal returns the caller's draft intact. */
export async function saveTask(
  task: string,
  base: TaskRecord,
  draft: TaskRecord,
  evidence: Record<number, string>,
  fetcher: typeof apiFetch = apiFetch,
): Promise<SaveResult> {
  const diff = changedFields(base, draft);
  const checked = newlyChecked(base, draft);
  const missingEvidence = checked.filter((n) => !evidence[n]?.trim());
  if (missingEvidence.length) return { ok: false, missingEvidence, record: draft };
  if (!diff.fields.length) return { ok: true, changed: [], record: draft };
  const comment = checked.map((n) => `AC #${n}: ${evidence[n].trim()}`).join("\n");
  let response: Response;
  try {
    response = await fetcher("/api/edit", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ task, base: diff.base, changes: withoutNew(diff.changes), comment, actor: PAGE_ACTOR }),
    });
  } catch {
    return { ok: false, reason: "The task writer could not be reached.", skill: "", fields: diff.fields, record: draft };
  }
  const body = await response.json().catch(() => ({})) as { changed?: TaskField[]; error?: string; skill?: string; stale?: TaskField[] };
  if (response.ok) return { ok: true, changed: body.changed ?? diff.fields, record: draft };
  return {
    ok: false,
    reason: body.error ?? `The task writer answered ${response.status}.`,
    skill: body.skill ?? "",
    fields: body.stale?.length ? body.stale : diff.fields,
    record: draft,
  };
}

/** The parts of the task the view edits one at a time, each owning the record fields its Save writes. */
export type Section = "title" | "description" | "acceptanceCriteria" | "definitionOfDone" | "plan" | "notes" | "details";
export const SECTION_FIELDS: Record<Section, TaskField[]> = {
  title: ["title"], description: ["description"], acceptanceCriteria: ["acceptanceCriteria"], definitionOfDone: ["definitionOfDone"],
  plan: ["plan"], notes: ["notes"], details: ["profile", "priority", "labels", "milestone"],
};

/** How a section is named in its ✎ label and in the toast that confirms its save. */
export const SECTION_NAMES: Record<Section, string> = {
  title: "title", description: "description", acceptanceCriteria: "acceptance criteria", definitionOfDone: "definition of done",
  plan: "implementation plan", notes: "notes", details: "details",
};

/** Save one section: the guarded write carries that section's diff and nothing else the draft holds. A result's `record` is the base with that section applied. */
export async function saveSection(
  task: string, section: Section, base: TaskRecord, draft: TaskRecord, evidence: Record<number, string>, fetcher: typeof apiFetch = apiFetch,
): Promise<SaveResult> {
  const scoped = { ...base, ...Object.fromEntries(SECTION_FIELDS[section].map((field) => [field, draft[field]])) } as TaskRecord;
  // the board refuses a checklist item with no text, so a row added and left empty is not part of the write
  scoped.acceptanceCriteria = scoped.acceptanceCriteria.filter((item) => item.text.trim());
  scoped.definitionOfDone = scoped.definitionOfDone.filter((item) => item.text.trim());
  return saveTask(task, base, scoped, evidence, fetcher);
}

/** The record with one checklist item checked or unchecked: the direct toggle, which needs no editor. */
export function toggleItem(record: TaskRecord, field: "acceptanceCriteria" | "definitionOfDone", n: number, checked: boolean): TaskRecord {
  return { ...record, [field]: record[field].map((item) => item.n === n ? { ...item, checked } : item) };
}

export type EditAction = "save" | "cancel";

/** The open editor's document-level shortcuts. */
export function editKey(key: string, ctrl: boolean, meta: boolean): EditAction | null {
  if (key === "Escape") return "cancel";
  if (key === "Enter" && (ctrl || meta)) return "save";
  return null;
}

export const PRIORITIES = ["High", "Medium", "Low"];

/** The first-class fields the board stores as a `<field>-<value>` label, with the values the Details select offers (doc-993 D10). */
export const LABEL_FIELDS = { kind: ["execute", "decide", "investigate", "verify"], size: ["1", "2", "3", "5", "8"], area: [] as string[], mode: ["attended", "unattended"] };
export type LabelField = keyof typeof LABEL_FIELDS;
const LABEL_FIELD_NAMES = Object.keys(LABEL_FIELDS) as LabelField[];
const TRIAL = "trial-";
/** The label rule as the Add label control states it before anything is typed (doc-993 D11). */
export const LABEL_RULE = "kebab-case · 3 words · 24 chars · no dates or ids";

const fieldOf = (label: string) => LABEL_FIELD_NAMES.find((field) => label.startsWith(`${field}-`));

/** A record's labels as Details draws them: each field's value (the first label of its prefix, "" when none) and the free-form labels as chips. */
export function detailFields(labels: string[]): Record<LabelField, string> & { chips: string[] } {
  const value = (field: LabelField) => labels.find((label) => fieldOf(label) === field)?.slice(field.length + 1) ?? "";
  return {
    kind: value("kind"), size: value("size"), area: value("area"), mode: value("mode"),
    chips: labels.filter((label) => !fieldOf(label) && !label.startsWith(TRIAL)),
  };
}

/** The labels with `field` set to `value`: its label replaced in place, any second label of its prefix dropped, and none left for an empty value. */
export function setDetailField(labels: string[], field: LabelField, value: string): string[] {
  const first = labels.findIndex((label) => fieldOf(label) === field);
  const next = value ? `${field}-${value}` : null;
  const rest = labels.map((label, i) => fieldOf(label) === field ? (i === first ? next : null) : label);
  return (first < 0 && next ? [...rest, next] : rest).filter((label): label is string => label !== null);
}

/** Why the board would refuse a free-form `label`, in the words the control shows as it is typed; "" when it passes. */
export function labelRuleError(label: string): string {
  const field = LABEL_FIELD_NAMES.find((name) => label.startsWith(`${name}-`));
  if (field) return `${field}- is a field; set ${field} above.`;
  const words = label.split("-").length;
  const dated = /\d{3,}/.test(label) ? " Dates and ids go in meta." : "";
  if (label.length > 24 || words > 3) return `"${label}" is ${label.length} chars, ${words} words; labels are 3 words, 24 chars at most.${dated}`;
  if (dated) return `"${label}" carries a date or id.${dated}`;
  if (!/^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.test(label)) return `"${label}" is not kebab-case: lowercase words joined by hyphens.`;
  return "";
}
/** The levels of a task's Impact and Urgency, which the scheduler's Priority matrix maps to a weight. */
export const LEVELS = ["high", "medium", "low"];

/** The task's record from the server, or null when the board cannot read it or the request failed. */
export async function fetchRecord(id: string, fetcher: typeof apiFetch = apiFetch): Promise<TaskRecord | null> {
  try {
    const response = await fetcher(`/api/task/${encodeURIComponent(id)}`);
    if (!response.ok) return null;
    const body: { record?: TaskRecord } | null = await response.json().catch(() => null);
    return body?.record ?? null;
  } catch {
    return null;
  }
}

/** A milestone as `GET /api/milestones/<id>` gives it, less its sections. */
export interface MilestoneDoc { id: string; title: string; description: string; specs: string[] }

/** A doc as `GET /api/docs` lists it. */
export interface DocSummary { id: string; title: string; type: string }

/** One row of the rail's Docs: `id` is empty for a linked file the board does not serve, and such a row does not open. */
export interface DocLink { kind: "Milestone" | "Spec" | "Doc"; id: string; title: string; openable: boolean }

async function getJson<T>(url: string, key: string, fetcher: typeof apiFetch): Promise<T | null> {
  try {
    const response = await fetcher(url);
    const body = response.ok ? (await response.json().catch(() => null)) as Record<string, T> | null : null;
    return body?.[key] ?? null;
  } catch {
    return null;
  }
}

export const fetchMilestone = (id: string, fetcher: typeof apiFetch = apiFetch) =>
  getJson<MilestoneDoc>(`/api/milestones/${encodeURIComponent(id)}`, "milestone", fetcher);
export const fetchDocs = async (fetcher: typeof apiFetch = apiFetch): Promise<DocSummary[]> =>
  (await getJson<DocSummary[]>("/api/docs", "docs", fetcher)) ?? [];
export const fetchDoc = (id: string, fetcher: typeof apiFetch = apiFetch) =>
  getJson<DocSummary & { body: string }>(`/api/docs/${encodeURIComponent(id)}`, "doc", fetcher);

/** The doc a board file name or a milestone's Spec bullet starts with (`doc-993 - Title.md`, `doc-993 — path`), else empty. */
const docId = (text: string): string => /^(doc-\d+)\b/.exec(text)?.[1] ?? "";

/**
 * The rail's Docs rows for a record: its milestone, that milestone's specs, then the docs it links, each doc once. A title is the
 * listed doc's, else the file's name; the milestone row opens once the milestone has been read.
 */
export function docLinks(record: Pick<TaskRecord, "milestone" | "documentation">, milestone: MilestoneDoc | null, docs: DocSummary[]): DocLink[] {
  const listed = new Map(docs.map((d) => [d.id, d]));
  const specs = new Set((milestone?.specs ?? []).map(docId).filter(Boolean));
  const links: DocLink[] = record.milestone
    ? [{ kind: "Milestone", id: record.milestone, title: milestone?.title ?? record.milestone, openable: milestone !== null }]
    : [];
  const seen = new Set<string>();
  for (const entry of [...specs, ...(record.documentation ?? [])]) {
    const name = entry.split("/").pop()!.replace(/\.md$/, "");
    const id = docId(name);
    if (id && seen.has(id)) continue;
    seen.add(id);
    const doc = listed.get(id);
    links.push({ kind: specs.has(id) || doc?.type === "specification" ? "Spec" : "Doc", id, title: doc?.title ?? (name.replace(/^doc-\d+ - /, "") || name), openable: Boolean(doc) });
  }
  return links;
}

/** Milliseconds a record read while the pointer rested on its card stays fresh enough for its modal to draw without reading again. */
export const READ_AHEAD_MS = 10_000;

/** Milliseconds the pointer rests on a card before its modal is drawn hidden, so a pointer passing over cards draws none. */
export const PRE_DRAW_REST_MS = 80;

/** A record read ahead: when it was asked for, the read, and its result once that has landed. */
export interface HeldRecord { at: number; read: Promise<TaskRecord | null>; got?: TaskRecord | null }

/**
 * Records read while the pointer rests on a card, so the click draws the whole record at once instead of the snapshot's
 * entry and a request later. A read is held for `READ_AHEAD_MS`, as fresh as a modal opened when the hover began.
 */
export class RecordCache {
  private held = new Map<string, HeldRecord>();
  constructor(private fetcher: typeof apiFetch = apiFetch, private clock: () => number = Date.now) {}

  /** Read `id`'s record ahead with `fetcher`, unless a fresh read of it is already held. */
  readAhead(id: string, fetcher: typeof apiFetch = this.fetcher): void {
    if (this.fresh(id)) return;
    const held: HeldRecord = { at: this.clock(), read: fetchRecord(id, fetcher) };
    void held.read.then((record) => { held.got = record; });
    this.held.set(id, held);
  }

  /** The fresh read held for `id`, if any. */
  fresh(id: string): HeldRecord | undefined {
    const held = this.held.get(id);
    return held && this.clock() - held.at < READ_AHEAD_MS ? held : undefined;
  }

  /** The read held for `id` however old, to seed a modal that reads the record again anyway. */
  last(id: string): HeldRecord | undefined {
    return this.held.get(id);
  }

  /** Drop `id`'s read, once a save has made it stale. */
  forget(id: string): void {
    this.held.delete(id);
  }
}

export interface MenuState { open: boolean; on: number }
export interface MenuStep {
  state: MenuState;
  /** The index of the item chosen, when the key chose one. */
  pick: number | null;
  /** Whether the menu used the key, so the page must not: Escape closes only the menu, not the task view. */
  handled: boolean;
}

/** What a key does to the Move to menu whose items are enabled as `enabled` says. */
export function menuKey(state: MenuState, key: string, enabled: boolean[]): MenuStep {
  const n = enabled.length;
  const shut: MenuState = { open: false, on: -1 };
  if (!state.open) {
    if (!n || (key !== "ArrowDown" && key !== "ArrowUp")) return { state, pick: null, handled: false };
    return { state: { open: true, on: key === "ArrowUp" ? n - 1 : 0 }, pick: null, handled: true };
  }
  switch (key) {
    case "Escape": return { state: shut, pick: null, handled: true };
    case "ArrowDown": return { state: { open: true, on: (state.on + 1) % n }, pick: null, handled: true };
    case "ArrowUp": return { state: { open: true, on: (state.on + n - 1) % n }, pick: null, handled: true };
    case "Enter":
    case " ": return enabled[state.on] ? { state: shut, pick: state.on, handled: true } : { state, pick: null, handled: true };
    case "Tab": return { state: shut, pick: null, handled: false };
    default: return { state, pick: null, handled: false };
  }
}

/** The text Copy puts on the clipboard: the task's id and its title. */
export const copyText = (task: { id: string }, title: string): string => `${task.id} ${title}`;

/** Write `text` to the clipboard; false when the browser refuses. A page served over plain http has no async clipboard, so a selection copy stands in. */
export async function copyToClipboard(text: string, clipboard: Pick<Clipboard, "writeText"> | undefined = globalThis.navigator?.clipboard): Promise<boolean> {
  try {
    if (clipboard) {
      await clipboard.writeText(text);
      return true;
    }
  } catch {
    // refused: fall back to a selection copy
  }
  if (typeof document === "undefined") return false;
  const box = document.createElement("textarea");
  box.value = text;
  box.style.cssText = "position:fixed;opacity:0";
  document.body.append(box);
  box.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    box.remove();
  }
}

/** A press on the dimmed scrim, not on the dialog above it, dismisses the modal. */
export const onScrim = (target: unknown, scrim: unknown): boolean => target === scrim;

/** Escape closes the modal, except in the edit form, whose own shortcuts own it. */
export const closesOnKey = (key: string, editing: boolean): boolean => key === "Escape" && !editing;

export type Block =
  | { kind: "p" | "h" | "moved"; text: string }
  | { kind: "pre"; lang: string; text: string }
  | { kind: "table"; head: string[]; right: boolean[]; rows: string[][] };

/** What the description's `start_criteria` block gives way to once the rail draws the criteria. */
export const CRITERIA_POINTER = "Start Criteria are drawn in the side panel, each with its result →";

/** A GFM table's delimiter row: `|---|:---:|--:|`, with or without outer pipes. */
const DELIMITER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
/** The cells of one table row, its outer pipes dropped. */
const cells = (line: string): string[] => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());

/** A task description's Markdown as the blocks the read view draws: paragraphs, `##` headings, fenced code and GFM tables; with `drawn`, the `start_criteria` block is a pointer to the rail. */
export function markdown(text: string, drawn = false): Block[] {
  const blocks: Block[] = [];
  const lines = text.split("\n");
  let para: string[] = [];
  let fence = false;
  let lang = "";
  const flush = (kind: "p" | "pre") => {
    const text = para.join("\n");
    if (kind === "pre") blocks.push({ kind, lang, text });
    else if (para.length) blocks.push({ kind, text });
    para = [];
  };
  for (let at = 0; at < lines.length; at++) {
    const line = lines[at];
    if (line.startsWith("```")) {
      flush(fence ? "pre" : "p");
      const last = blocks[blocks.length - 1];
      if (drawn && fence && last.kind === "pre" && /^start_criteria:/m.test(last.text)) blocks[blocks.length - 1] = { kind: "moved", text: CRITERIA_POINTER };
      lang = line.slice(3).trim();
      fence = !fence;
    } else if (fence) para.push(line);
    else if (line.startsWith("## ")) {
      flush("p");
      blocks.push({ kind: "h", text: line.slice(3) });
    } else if (/^\s*\|/.test(line) && DELIMITER.test(lines[at + 1] ?? "")) {
      flush("p");
      const right = cells(lines[at + 1]).map((c) => c.endsWith(":"));
      const rows: string[][] = [];
      for (at += 2; at < lines.length && /^\s*\|/.test(lines[at]); at++) rows.push(cells(lines[at]));
      at--;
      blocks.push({ kind: "table", head: cells(line), right, rows });
    } else if (line.trim()) para.push(line);
    else flush("p");
  }
  flush(fence ? "pre" : "p");
  return blocks;
}

/** The `## ` sections a task's creation writes as its own bookkeeping; the dialog does not draw them. */
const CREATION_SECTIONS = ["Duplicate Search", "Duplicate Resolution", "ADR Needed"];

/** The body sections the dialog draws for a record: the description without its creation sections, and the notes without the claim marker. */
export function taskBody(record: TaskRecord): Pick<TaskRecord, "description" | "notes"> {
  let skip = false;
  let fence = false;
  const description: string[] = [];
  for (const line of record.description.split("\n")) {
    if (line.startsWith("```")) fence = !fence;
    else if (!fence && line.startsWith("## ")) skip = CREATION_SECTIONS.includes(line.slice(3).trim());
    if (!skip) description.push(line);
  }
  const notes = record.notes.split("\n").filter((line) => !line.startsWith("**Assignee:**")).join("\n");
  return { description: description.join("\n").trim(), notes: notes.trim() };
}

/** How many of the tasks a task holds the rail lists before it counts the rest. */
export const HOLDS_SHOWN = 6;

/** One task the rail's Dependencies section names: its id, its title and lane, or null for both when it is not on the board. */
export interface DepRow { id: string; title: string | null; lane: string | null }

/** What a task depends on, and the tasks that depend on it (the first six, with how many more follow). */
export function dependencyRows(tasks: KanbanTask[], task: KanbanTask): { dependsOn: DepRow[]; holds: DepRow[]; more: number } {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const row = (id: string): DepRow => ({ id, title: byId.get(id)?.title ?? null, lane: byId.get(id)?.lane ?? null });
  const held = tasks.filter((t) => t.dependencies.includes(task.id));
  return { dependsOn: task.dependencies.map(row), holds: held.slice(0, HOLDS_SHOWN).map((t) => row(t.id)), more: Math.max(0, held.length - HOLDS_SHOWN) };
}

/** How many criteria are met. */
export const metCount = (criteria: StartCriterion[]): number => criteria.filter((c) => c.status === "met").length;

/** A `time()` criterion waits for a moment, not a measurement. */
const waitsForTime = (c: StartCriterion): boolean => c.expr.replace(/\s/g, "") === "time()" && c.cmp === "at_least" && typeof c.want === "number";

/** `threshold · last value · checked <age>` for a criterion, or `opens <date MST>` for a `time()` one; parts it lacks are left out. */
export function criterionDetail(c: StartCriterion, now: number): string {
  const checked = c.checked ? Date.parse(c.checked) / 1000 : NaN;
  const threshold = waitsForTime(c) ? `opens ${fmtAt(c.want as number)} MST` : c.cmp ? `${c.cmp.replace("_", " ")} ${String(c.want)}` : "";
  const last = c.status === "error" || waitsForTime(c) || c.observed == null ? "" : `last ${String(c.observed)}`;
  return [threshold, last, Number.isNaN(checked) ? "" : `checked ${ago(now - checked)} ago`].filter(Boolean).join(" · ");
}

/** What one pull request put its CI through, counted by the D10 definitions: a run is a push, a rebase and a re-run are counted apart. */
export interface CiPull { number: number | null; url: string | null; runs: number; reruns: number; rebases: number; conflicts: number; state: string }
export interface CiHistory { pulls: CiPull[]; total: Pick<CiPull, "runs" | "reruns" | "rebases" | "conflicts"> }

const CI_COUNTED = { PUSHED: "runs", RERUN: "reruns", REBASED: "rebases", CONFLICTED: "conflicts" } as const;
/** A CI step's id is `ci:<pull url>:<kind>[:sha]`: the pull request it moved, as its url and number. */
const CI_PULL = /^ci:(.+\/pull\/(\d+))(?::|$)/;

/**
 * The CI history of a task from its `ci` machine's trail, or null when it is in no such machine. Each step names the pull request it
 * moved in its id, so a step counts on that pull request alone: a closed one the task no longer lists gets a row of its own (linked by
 * the url its id holds) and shifts no other's counts. A step with no id counts on the latest pull request, or on the task's newest.
 */
export function ciHistory(task: KanbanTask): CiHistory | null {
  const trail = task.machines.find((m) => m.machine === "ci")?.trail;
  if (!trail) return null;
  const newest = [...task.prs].sort((a, b) => b.number - a.number)[0];
  const pulls: CiPull[] = [];
  const pullOf = (number: number | null, url: string | null) => {
    let pull = pulls.find((p) => p.number === number);
    if (!pull) pulls.push((pull = { number, url, runs: 0, reruns: 0, rebases: 0, conflicts: 0, state: "" }));
    return pull;
  };
  for (const step of trail) {
    const named = CI_PULL.exec(step.id ?? "");
    const number = named ? Number(named[2]) : null;
    const listed = task.prs.find((p) => p.number === number);
    const pull = named ? pullOf(number, listed?.url ?? named[1]) : (pulls.at(-1) ?? pullOf(newest?.number ?? null, newest?.url ?? null));
    const counted = CI_COUNTED[step.event as keyof typeof CI_COUNTED];
    if (counted) pull[counted]++;
    pull.state = step.state;
  }
  const sum = (key: keyof CiHistory["total"]) => pulls.reduce((n, p) => n + p[key], 0);
  return { pulls, total: { runs: sum("runs"), reruns: sum("reruns"), rebases: sum("rebases"), conflicts: sum("conflicts") } };
}

/** The pull requests the CI trail names that the task's list does not (a closed one): the panel draws each as a row of its own. */
export const unlistedPulls = (task: KanbanTask, history: CiHistory | null): CiPull[] =>
  (history?.pulls ?? []).filter((c) => !task.prs.some((p) => p.number === c.number));

/** What the Session section draws for a task: the claiming session's link and id, and the line the in-progress machine gives it. */
export interface SessionView { url: string; line: string; id: string }

/**
 * The session that holds `task`, or null when none does. A startable task is held by no one, so the link an earlier
 * session left on it is ignored; the line (model, state, age, steps) is whatever the in-progress machine reports.
 */
export function sessionOf(task: KanbanTask, record: TaskRecord | null, now: number, startLane: boolean): SessionView | null {
  const url = startLane ? "" : record?.session ?? "";
  if (!url) return null;
  const machine = task.machines.find((m) => m.machine === "in-progress" && m.at > 0);
  const steps = machine?.steps ?? 0;
  const line = machine ? [machine.model, machine.state.replace(/_/g, " "), `${ago(now - machine.at)} ago`, `${steps} step${steps === 1 ? "" : "s"}`].filter(Boolean).join(" · ") : "";
  return { url, line, id: url.split("/").pop()!.replace(/^session_/, "") };
}
