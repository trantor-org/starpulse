// The titles of tasks the snapshot no longer holds: it carries only the day's settled tasks, so an older merge's task is read from its record.

import { fetchRecord } from "../features/kanban/taskViewModel";

export class TaskTitles {
  /** Each task asked for: its title once its record is read, undefined when it has none to give. */
  private readonly held = new Map<string, string | undefined>();

  constructor(
    /** Draw again: a record arrived. */
    private readonly wake: () => void,
    private readonly read: typeof fetchRecord = fetchRecord,
  ) {}

  /** The title of task `id` if its record has been read, else undefined, and asks for the record the first time. */
  of(id: string): string | undefined {
    if (this.held.has(id)) return this.held.get(id);
    this.held.set(id, undefined);
    void this.read(id).then((record) => {
      this.held.set(id, record?.title || undefined);
      this.wake();
    });
    return undefined;
  }
}
