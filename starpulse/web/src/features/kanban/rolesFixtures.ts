// A Board whose States are renamed, and the roles its machine declares (the wire form of `renamed-board.yaml`): the page reads the roles, never a State's name.
import type { Roles } from "../../api";
import type { KanbanTask } from "./kanbanModel";

export const RENAMED_NAMES: Record<string, string> = {
  inbox: "Inbox", todo: "To do", parked: "Parked", doing: "Doing", checking: "Checking", on_me: "On me", shipped: "Shipped", gone: "Gone",
};

export const RENAMED_ROLES: Roles = {
  initial: "inbox", final: "gone", done: "shipped", working: "doing", ready: "todo", waiting: "parked", review: "checking", attention: "on_me",
  startable: ["on_me", "parked", "todo"],
};

export const card = (id: string, lane: string, extra: Partial<KanbanTask> = {}): KanbanTask => ({
  id, title: `title ${id}`, lane, milestone: "m-1", labels: [], assignee: "", dependencies: [], openDeps: 0,
  prs: [], description: "", live: null, released: false, moves: {}, entered: 100, created: null, workableSince: null, machines: [], ...extra,
});
