import { describe, expect, it } from "vitest";
import { NO_PREFS, hideMilestone, hideTask, toggleFold, type Prefs } from "./kanban";
import { PREFS_KEY, linkedTask, loadPrefs, savePrefs, withoutFilters } from "./kanbanPrefs";
import type { PrefStorage } from "../../shared/nav";

const memory = (): PrefStorage & { data: Map<string, string> } => {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
};
const chosen: Prefs = hideTask(hideMilestone(toggleFold({ ...NO_PREFS, query: "label:size-3 kanban", assignee: "@agent-deep-high", milestone: "" }, "m-76"), "m-9"), "PROJ-1");
const plain = (p: Prefs) => ({ ...p, folded: [...p.folded], hiddenMilestones: [...p.hiddenMilestones], hiddenTasks: [...p.hiddenTasks] });

describe("the view's persistence", () => {
  it("starts from nothing chosen when storage holds nothing", () => {
    expect(loadPrefs(memory(), "")).toEqual(NO_PREFS);
  });

  it("brings back the filters, hidden items and folds after a reload", () => {
    const storage = memory();
    savePrefs(storage, chosen);

    expect(plain(loadPrefs(storage, ""))).toEqual(plain(chosen));
  });

  it("keeps the unassigned and No milestone choices apart from no choice", () => {
    const storage = memory();
    savePrefs(storage, { ...NO_PREFS, assignee: "", milestone: "" });

    expect(loadPrefs(storage, "")).toMatchObject({ assignee: "", milestone: "" });
  });

  it.each([["not json"], ["null"], ['{"query": 7, "folded": "m-1", "hiddenTasks": [1, "PROJ-2"]}']])("falls back to what it can read from %s", (text) => {
    const storage = memory();
    storage.data.set(PREFS_KEY, text);
    const prefs = loadPrefs(storage, "");

    expect(prefs.query).toBe("");
    expect(prefs.assignee).toBeNull();
    expect([...prefs.folded]).toEqual([]);
    expect([...prefs.hiddenTasks].every((id) => typeof id === "string")).toBe(true);
  });

  it("still works for the session when storage is off or absent", () => {
    const off: PrefStorage = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("denied"); } };

    expect(loadPrefs(off, "")).toEqual(NO_PREFS);
    expect(() => savePrefs(off, chosen)).not.toThrow();
    expect(loadPrefs(null, "")).toEqual(NO_PREFS);
    expect(() => savePrefs(null, chosen)).not.toThrow();
  });
});

describe("a deep link", () => {
  const stored = () => {
    const storage = memory();
    savePrefs(storage, chosen);
    return storage;
  };

  it("starts from its own filters and drops the stored ones, hidden items and folds with them", () => {
    const prefs = loadPrefs(stored(), "?view=kanban&q=label%3Aneeds-human&assignee=%40agent-standard-high&milestone=m-76");

    expect(plain(prefs)).toEqual(plain({ ...NO_PREFS, query: "label:needs-human", assignee: "@agent-standard-high", milestone: "m-76" }));
  });

  it("leaves a filter it does not name unset rather than taking the stored one", () => {
    expect(plain(loadPrefs(stored(), "?q=kanban"))).toEqual(plain({ ...NO_PREFS, query: "kanban" }));
  });

  it("reads an empty assignee or milestone as unassigned or No milestone", () => {
    expect(loadPrefs(stored(), "?view=kanban&assignee&milestone=")).toMatchObject({ assignee: "", milestone: "" });
  });

  it("is not a deep link without one of its three parameters: the stored view wins", () => {
    expect(plain(loadPrefs(stored(), "?view=kanban&demo"))).toEqual(plain(chosen));
  });

  it("leaves the address with every other parameter once the view has taken the state", () => {
    expect(withoutFilters("?view=kanban&q=x&demo&assignee=a&milestone=m-1")).toBe("?view=kanban&demo");
    expect(withoutFilters("?q=x")).toBe("");
    expect(withoutFilters("?view=kanban&demo")).toBe("?view=kanban&demo");
  });
});

describe("a link to one task", () => {
  it("names the task whose modal the view opens with", () => {
    expect(linkedTask("?view=kanban&task=PROJ-7")).toBe("PROJ-7");
    expect(linkedTask("?view=kanban")).toBeNull();
  });

  it("leaves the address once taken, so a reload does not reopen it", () => {
    expect(withoutFilters("?view=kanban&task=PROJ-7&demo")).toBe("?view=kanban&demo");
  });
});
