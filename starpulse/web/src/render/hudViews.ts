// The Kanban and DAGs HUD fields load on the first snapshot, so the Star Map's first paint does not wait for their code.
type DagDataFn = (typeof import("../features/dags/dagsModel"))["dagData"];
type KanbanTasksFn = (typeof import("../features/kanban/kanbanModel"))["kanbanTasks"];
export let dagData: DagDataFn | null = null;
export let kanbanTasks: KanbanTasksFn | null = null;
let hudViewsP: Promise<void> | undefined;
export const loadHudViews = (): Promise<void> => (hudViewsP ??= Promise.all([
  import("../features/dags/dagsModel"),
  import("../features/kanban/kanbanModel"),
]).then(([d, k]) => {
  dagData = d.dagData;
  kanbanTasks = k.kanbanTasks;
}));
