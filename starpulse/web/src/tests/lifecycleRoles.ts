import type { Roles } from "../api";

/** The roles the trantor lifecycle's States play, as its server publishes them on the snapshot. */
export const LIFECYCLE_ROLES: Roles = {
  initial: "new", final: "completed", done: "done", working: "in_progress", ready: "ready", waiting: "waiting", review: "review", attention: "needs_attention",
  startable: ["needs_attention", "ready", "waiting"],
};

/** The columns the trantor lifecycle draws, in order. */
export const LIFECYCLE_COLUMNS = ["ready", "waiting", "in_progress", "review", "needs_attention", "done"];
