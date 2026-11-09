import { describe, expect, it, vi } from "vitest";
import type { TaskRecord } from "../features/kanban/taskViewModel";
import { TaskTitles } from "./taskTitles";

const record = (title: string) => ({ title }) as TaskRecord;

describe("the titles of tasks the snapshot does not hold", () => {
  it("reads a task's title from its record once, then draws again with it", async () => {
    const wake = vi.fn();
    const read = vi.fn(async () => record("An old task"));
    const titles = new TaskTitles(wake, read);

    expect(titles.of("PROJ-1")).toBeUndefined();
    expect(titles.of("PROJ-1")).toBeUndefined();
    await vi.waitFor(() => expect(wake).toHaveBeenCalledTimes(1));

    expect(titles.of("PROJ-1")).toBe("An old task");
    expect(read).toHaveBeenCalledTimes(1);
  });

  it("does not read again for a task whose record the board could not give", async () => {
    const wake = vi.fn();
    const read = vi.fn(async () => null);
    const titles = new TaskTitles(wake, read);

    titles.of("PROJ-2");
    await vi.waitFor(() => expect(wake).toHaveBeenCalledTimes(1));
    titles.of("PROJ-2");

    expect(titles.of("PROJ-2")).toBeUndefined();
    expect(read).toHaveBeenCalledTimes(1);
  });
});
