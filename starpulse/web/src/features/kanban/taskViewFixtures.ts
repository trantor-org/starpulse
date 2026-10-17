import type { KanbanTask } from "./kanbanModel";
import type { TaskView } from "./TaskView";
import type { TaskRecord } from "./taskViewModel";

/** Test fixtures shared by the task view's test files. */
export const task: KanbanTask = {
  id: "TASK-9", title: "Redraw the view", lane: "ready", milestone: "m-89", labels: ["needs-review"], assignee: "@agent-standard-high",
  dependencies: ["TASK-1"], openDeps: 0, runs: [], prs: [{ number: 12, url: "http://pr/12", checks: "pass", merged: false, merge_sha: null, merged_at: null, threads: 0, behind_main: null, stale: false }],
  description: "from the snapshot", live: null, released: false, entered: 700, created: 100, workableSince: null,
  machines: [{ machine: "in-progress", state: "pr_opened", at: 900, trail: [] }],
  moves: { in_progress: { allowed: true, reason: "", skill: "" }, review: { allowed: false, reason: "no review yet", skill: "completing-tasks" } },
};
export const record: TaskRecord = {
  title: "Redraw the view", profile: "@agent-standard-high", priority: "High", labels: ["needs-review"], milestone: "m-89", dependencies: ["TASK-1"],
  description: "the full description", plan: "1. Write the test\n2. Make it pass", notes: "Checked against the live config",
  acceptanceCriteria: [{ n: 1, text: "A Vitest test failed first", checked: true }, { n: 2, text: "make lint-changed passes", checked: false }],
  definitionOfDone: [{ n: 1, text: "The completing-tasks skill was invoked", checked: false }],
  session: "",
};
export const card = (id: string, lane: string, over: Partial<KanbanTask> = {}): KanbanTask => ({ ...task, id, title: `title ${id}`, lane, dependencies: [], prs: [], runs: [], machines: [], ...over });
export const board = [card("TASK-1", "done"), task];
export const props = (over: Partial<Parameters<typeof TaskView>[0]> = {}): Parameters<typeof TaskView>[0] => ({
  task, record, lane: "Ready", now: 1000, tasks: board, open: () => {}, profiles: [], milestones: [], refusal: null, startNote: null,
  names: { ready: "Ready", done: "Done", review: "Review" }, capabilities: { edit: true, archive: true }, saving: false, claiming: false,
  close: () => {}, hide: () => {}, constellation: () => {}, move: () => {}, start: () => {}, ...over,
});
