// @vitest-environment jsdom
// @ts-expect-error Vitest runs this test in Node; production source stays browser-only.
import { readFileSync } from "node:fs";
// @ts-expect-error Same Node-only import: jsdom swaps the global URL for one readFileSync refuses.
import { URL as NodeURL } from "node:url";
import { act, Profiler } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { KanbanTask } from "./kanbanModel";
import type { Pull } from "../../api";
import { TaskView } from "./TaskView";
import { sessionNickname } from "./nickname";
import { board, card, props, record, task } from "../../tests/taskViewFixtures";
import { closesOnKey, copyText, copyToClipboard, menuKey, onScrim, type StartCriterion } from "./taskViewModel";

const styles = readFileSync(new NodeURL("../../style.css", import.meta.url), "utf8");

const draw = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => renderToStaticMarkup(<TaskView {...props(over)} />);
const railOf = (html: string) => html.slice(html.indexOf('class="tvcol tvrail"'));
const headings = (html: string) => [...railOf(html).matchAll(/<span class="t">([^<]+)<\/span>/g)].map((m) => m[1]);

const headOf = (html: string) => html.slice(html.indexOf('class="tvhead"'), html.indexOf('class="tvbody"'));
const lanes = (lane: string, over: Partial<KanbanTask> = {}) => ({ task: { ...task, lane, ...over }, lane });

describe("the task view in read mode", () => {
  it("draws the plan, notes and checks the record carries", () => {
    const html = draw();

    expect(html).toContain("1. Write the test");
    expect(html).toContain("Checked against the live config");
    expect(html).toContain("A Vitest test failed first");
    expect(html).toContain("The completing-tasks skill was invoked");
    expect(html).toContain("1/2");
  });

  it("frames the title, locked against input, draws the details as plain text and the long text unframed", () => {
    const html = draw();
    const framed = html.match(/class="fv[ "][^>]*>/g) ?? [];

    expect(framed).toHaveLength(1);
    expect(html.match(/<textarea[^>]*data-field="title"[^>]*>/)![0]).toContain('readOnly=""');
    expect(railOf(html)).not.toMatch(/<(select|textarea)/);
    expect(html).not.toMatch(/<textarea[^>]*data-field="(description|plan|notes)"/);
    expect(html).not.toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/);
    expect(draw({ capabilities: { edit: false, archive: false } })).toMatch(/<input[^>]*type="checkbox"[^>]*disabled=""/);
  });

  it("draws Edit and Archive only when the board can", () => {
    expect(draw()).toContain("Archive…");
    expect(draw()).toContain("Edit");
    const readOnly = draw({ capabilities: { edit: false, archive: false } });
    expect(readOnly).not.toContain("Archive…");
    expect(readOnly).not.toContain("Edit");
    expect(draw({ capabilities: undefined })).not.toContain("Archive…");
  });

  it("selects the priority's own option when the board stores it in lower case", () => {
    const html = draw({ record: { ...record, priority: "high" }, initialEditing: "details" });

    expect(html).toContain('<option value="High" selected="">High</option>');
    expect(html).not.toContain('<option value="high"');
  });

  it("falls back to the snapshot's fields until the record arrives", () => {
    const html = draw({ record: null });

    expect(html).toContain("from the snapshot");
    expect(html).not.toContain("Implementation plan");
  });
});

describe("the task view's header", () => {
  it("lists the Star Map greyed out, not as a link, at phone width", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query === "(max-width: 900px)", addEventListener() {}, removeEventListener() {} }));
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.body.appendChild(document.createElement("div")), root = createRoot(host);
    try {
      act(() => root.render(<TaskView {...props()} />));
      const entry = [...host.querySelectorAll(".tvhead *")].find((e) => e.textContent === "Open in Star Map ↗")!;
      expect(entry.tagName).toBe("SPAN");
      expect(entry.getAttribute("aria-disabled")).toBe("true");
      expect(host.querySelector('.tvhead a[href="/"]')).toBeNull();
    } finally {
      act(() => root.unmount());
      host.remove();
      vi.unstubAllGlobals();
    }
  });

  it("draws the id, Copy, lane, Open in Star Map and the actions in one row, with the title below", () => {
    const head = headOf(draw());
    const at = (text: string) => head.indexOf(text);

    for (const text of ["TASK-9", "Copy", ">Ready<", "Open in Star Map ↗", "▶ Start session", "Move to", "Hide task", "Archive…", 'aria-label="Close"']) expect(at(text), text).toBeGreaterThan(-1);
    const order = ["TASK-9", "Copy", ">Ready<", "Open in Star Map ↗", "▶ Start session", "Move to", "Hide task", "Archive…", 'aria-label="Close"'].map(at);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(at('data-field="title"')).toBeGreaterThan(at('aria-label="Close"'));
    expect(draw()).not.toContain('class="tvfoot"');
    // a <header> inside the board matches `#kb header`, which would centre the row and set the title in capitals
    expect(draw()).not.toMatch(/<header/);
  });

  it("offers Start session only from Ready, Waiting and Needs attention while no start is in flight", () => {
    for (const lane of ["ready", "waiting", "needs_attention"]) expect(headOf(draw(lanes(lane)))).toContain("▶ Start session");
    for (const lane of ["in_progress", "review", "done"]) expect(headOf(draw(lanes(lane)))).not.toContain("▶ Start session");
    expect(headOf(draw({ claiming: true }))).not.toContain("▶ Start session");
  });

  it("draws the Move to menu with a row per column the task has a verdict for", () => {
    const head = headOf(draw());

    expect(head).toContain('aria-haspopup="menu"');
    expect(head.match(/role="menuitem"/g)).toHaveLength(2);
    expect(head).toContain("no review yet");
    expect(head).toMatch(/class="mvmenu"[^>]*hidden=""/);
  });

  it("moves the task on the menu's Enter and closes the menu on Escape without closing the task", () => {
    expect(menuKey({ open: true, on: 1 }, "Enter", [true, true])).toEqual({ state: { open: false, on: -1 }, pick: 1, handled: true });
    expect(menuKey({ open: true, on: 0 }, "Escape", [true, true])).toMatchObject({ pick: null, handled: true, state: { open: false } });
  });

  it("copies 'TASK-N title' to the clipboard", async () => {
    const writeText = vi.fn(async () => {});

    expect(copyText(task, "A new title")).toBe("TASK-9 A new title");
    expect(await copyToClipboard("TASK-9 Redraw the view", { writeText })).toBe(true);
    expect(writeText).toHaveBeenCalledWith("TASK-9 Redraw the view");
    expect(await copyToClipboard("x", { writeText: async () => { throw new Error("refused"); } })).toBe(false);
    expect(await copyToClipboard("x", undefined)).toBe(false);
  });

  it("closes on a click outside the dialog or Escape, but not while editing", () => {
    const scrim = {}, dialog = {};

    expect(onScrim(scrim, scrim)).toBe(true);
    expect(onScrim(dialog, scrim)).toBe(false);
    expect(closesOnKey("Escape", false)).toBe(true);
    expect(closesOnKey("Escape", true)).toBe(false);
    expect(closesOnKey("Enter", false)).toBe(false);
  });
});

describe("the task view's body", () => {
  it("draws two columns: the read view on the left, the fields and live state in the rail", () => {
    const html = draw();
    const left = html.slice(html.indexOf('class="tvcol tvleft"'), html.indexOf('class="tvcol tvrail"'));
    const rail = html.slice(html.indexOf('class="tvcol tvrail"'));

    for (const text of ["Description", "Acceptance criteria", "1/2", "Definition of done", "0/1", "Implementation plan", "1. Write the test", "Notes", "Checked against the live config"]) expect(left, text).toContain(text);
    for (const text of ["Pull requests", "priority"]) expect(rail, text).toContain(text);
    expect(left).not.toContain("Pull requests");
  });

  it("draws the description as Markdown paragraphs, headings and code", () => {
    const html = draw({ record: { ...record, description: "First para\n\n## Background\n\nSecond para\n\n```yaml\nstart_criteria: []\n```" } });

    expect(html).toContain("<p>First para</p>");
    expect(html).toContain("<h4>Background</h4>");
    expect(html).toContain("<p>Second para</p>");
    expect(html).toContain("<pre>start_criteria: []</pre>");
  });

  it("sizes the dialog and scrolls each column on its own, stacking rail-first below 1100px", () => {
    expect(styles).toMatch(/#kbm \.modal\.tv \{[^}]*width: clamp\(860px, 65vw, 1500px\)[^}]*height: min\(84vh, 980px\)/);
    expect(styles).toMatch(/#kbm \.tvbody \{[^}]*grid-template-columns: minmax\(0, 1fr\) clamp\(320px, 31%, 440px\)/);
    // each column scrolls through the page's one scrolling rule (scroll.test.ts); below 1100px the body scrolls instead
    expect(styles).toMatch(/#kbm \.tvcol,[^{}]*\{[^}]*overflow-y: auto/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvbody \.tvcol \{[^}]*overflow: visible/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvbody \{[^}]*flex-direction: column;/);
    expect(styles).toMatch(/@media \(max-width: 1100px\) \{[^@]*#kbm \.tvrail \{[^}]*order: -1/);
    expect(styles).not.toMatch(/column-reverse/);
  });
});

describe("the task view's right rail", () => {
  const holder = (n: number) => card(`TASK-${100 + n}`, n % 2 ? "waiting" : "ready", { dependencies: ["TASK-9"] });
  const many = [...board, ...Array.from({ length: 8 }, (_, i) => holder(i + 1))];
  const trail = Array.from({ length: 7 }, (_, i) => ({ state: `step_${i}`, event: `event_${i}`, at: 800 + i }));
  const rows = (html: string, section: string) => railOf(html).split('<section').find((x) => x.includes(`<span class="t">${section}</span>`)) ?? "";

  it("draws Status, Pull requests, Dependencies, Docs and Details in that order, each heading with its count", () => {
    const html = draw({ tasks: many });

    expect(headings(html)).toEqual(["Status", "Session", "Pull requests", "Dependencies", "Docs", "Details"]);
    expect(rows(html, "Pull requests")).toContain('<span class="n">1</span>');
    expect(rows(html, "Dependencies")).toContain('<span class="n">9</span>');
    expect(rows(html, "Status")).not.toContain('class="n"');
    expect(styles).toMatch(/#kbm \.tvrail \.sec \+ \.sec \{[^}]*border-top: 1px solid/);
    expect(styles).toMatch(/#kbm \.tvrail \.props td:first-child \{[^}]*width: calc\(74px \* var\(--fs\)\)/);
    expect(styles).toMatch(/#kbm \.tv \.sh \{[^}]*text-transform: uppercase/);
  });

  it("draws the lane and the time in it under Status, and leaves the time out when the board gave none", () => {
    expect(rows(draw(), "Status")).toMatch(/class="tvlane sm" data-lane="ready" data-role="ready"><i><\/i>Ready<\/span><span class="k">for 5m<\/span>/);
    expect(rows(draw({ task: { ...task, entered: 0 } }), "Status")).not.toContain("for ");
  });

  describe("Session", () => {
    const link = "https://claude.ai/code/session_abc";
    const working = { ...task, lane: "in_progress", machines: [{ machine: "in-progress", state: "pr_opened", at: 900, model: "opus", steps: 7, trail: [] }] };
    const session = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => rows(draw({ record: { ...record, session: link }, ...over }), "Session");

    it("links the claiming session in a new tab, with the in-progress machine's model, state, age and steps under it", () => {
      const html = session({ task: working, lane: "In progress" });

      expect(html).toContain(`<a href="${link}" target="_blank" rel="noopener" class="big"><span class="p"></span>Open the claiming session ↗</a>`);
      expect(html).toContain('<div class="k">opus · pr opened · 2m ago · 7 steps</div>');
      expect(html).not.toContain("No session");
    });

    it("names a session holder by its nickname under Assignee, not its raw UUID or URL", () => {
      const uuid = "1491aced-f6da-42b1-9303-9c19adfcc87d";
      const byUuid = session({ task: { ...working, assignee: uuid }, lane: "In progress" });
      const byUrl = session({ task: { ...working, assignee: link }, lane: "In progress" });

      expect(byUuid).toContain(`<dt>Assignee</dt><dd>${sessionNickname(uuid)}</dd>`);
      expect(byUrl).toContain(`<dt>Assignee</dt><dd>${sessionNickname(link)}</dd>`);
    });

    it("links the session alone when no machine is working the task", () => {
      const html = session({ task: { ...working, machines: [] }, lane: "In progress" });

      expect(html).toContain("Open the claiming session ↗");
      expect(html).not.toContain('class="k"');
    });

    it("says no session holds the task, pointing a startable task to Start session and an In progress one to being worked by hand", () => {
      const none = (over: Partial<KanbanTask>, lane: string) => rows(draw({ record: { ...record, session: "" }, ...lanes(lane, over) }), "Session");

      expect(none({}, "ready")).toContain("No session holds this task. ▶ Start session, top right, opens one.");
      expect(none({}, "review")).toContain("No session holds this task</");
      expect(none({}, "in_progress")).toContain("No session has claimed it: worked by hand");
      expect(none({}, "ready")).not.toContain("Open the claiming session");
    });

    it("ignores the link a startable task keeps from a session that no longer holds it, and a record that is not read yet", () => {
      expect(session({ ...lanes("ready") })).toContain("No session holds this task. ▶ Start session");
      expect(rows(draw({ record: null, task: working }), "Session")).toContain("worked by hand");
    });
  });

  it("draws each pull request as a link with its checks, or merged, and no thread or behind-main text", () => {
    const prs = [{ ...task.prs[0], threads: 2, behind_main: 4 }, { ...task.prs[0], number: 13, url: "http://pr/13", merged: true, checks: "pass" as const }];
    const html = rows(draw({ task: { ...task, prs } }), "Pull requests");

    expect(html).toContain('<a href="http://pr/12" target="_blank" rel="noopener">o/r#12 ↗</a>');
    expect(html).toContain("checks pass");
    expect(html).not.toContain("open thread");
    expect(html).not.toContain("behind main");
    expect(html).toMatch(/<a href="http:\/\/pr\/13"[^>]*>o\/r#13 ↗<\/a><span class="chk merged"><i><\/i>merged<\/span>/);
    expect(html).not.toContain("no open threads");
    expect(rows(draw({ task: { ...task, prs: [] } }), "Pull requests")).toContain("None yet");
  });

  it("lists what the task depends on and what it holds, each row its id, title and lane", () => {
    const html = rows(draw({ tasks: many }), "Dependencies");

    expect(html.indexOf("Depends on")).toBeLessThan(html.indexOf("Holds"));
    expect(html).toMatch(/<button class="dep"><span class="id">TASK-1<\/span><span class="tt">title TASK-1<\/span><span class="tvlane sm" data-lane="done" data-role="done"><i><\/i>Done<\/span><\/button>/);
    expect(html).toContain("TASK-101");
    expect(rows(draw({ task: { ...task, dependencies: ["TASK-404"] } }), "Dependencies")).toContain("not on the board");
  });

  it("caps Holds at six rows and counts the rest", () => {
    const html = rows(draw({ tasks: many }), "Dependencies");

    expect(html.match(/<button class="dep">/g)).toHaveLength(7);
    for (const n of [101, 106]) expect(html).toContain(`TASK-${n}`);
    for (const n of [107, 108]) expect(html).not.toContain(`TASK-${n}`);
    expect(html).toContain("+2 more");
    expect(rows(draw({ tasks: many.slice(0, 5) }), "Dependencies")).not.toContain("more");
  });

  it("opens that task's modal when a dependency row is clicked", () => {
    const open = vi.fn();
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props({ tasks: many, open })} />));

    const buttons = [...host.querySelectorAll<HTMLButtonElement>(".tvrail button.dep")];
    act(() => buttons.find((b) => b.textContent?.includes("TASK-1") && !b.textContent.includes("TASK-10"))!.click());
    act(() => buttons.find((b) => b.textContent?.includes("TASK-103"))!.click());
    act(() => root.unmount());
    host.remove();

    expect(open.mock.calls).toEqual([["TASK-1"], ["TASK-103"]]);
  });

  it("leaves the machines' transitions to Activity and draws no Machines rail section", () => {
    const machines = [{ machine: "in-progress", state: "pr_opened", at: 900, trail }];
    const html = draw({ task: { ...task, machines } });

    expect(railOf(html)).not.toContain("Machines");
    expect(railOf(html)).not.toContain('class="machs"');
    expect(html).toContain("event_6");
  });

  it("draws the details as a read table, and when the task was created", () => {
    const html = rows(draw({ task: { ...task, created: 400 } }), "Details");

    for (const text of ["profile", "@agent-standard-high", "priority", "High", "labels", "milestone", "m-89", "created", "10m ago"]) expect(html, text).toContain(text);
    expect(html).toContain('<span class="chip">needs-review</span>');
    expect(rows(draw({ task: { ...task, created: null } }), "Details")).toMatch(/created<\/td><td><span class="k">—<\/span>/);
  });

  it("edits kind, size, area, mode, priority, profile and milestone in Details, and leaves Dependencies read-only", () => {
    const html = draw({ initialEditing: "details", tasks: many });

    expect(rows(html, "Details")).toMatch(/data-field="priority"[\s\S]*data-field="profile"[\s\S]*data-field="milestone"/);
    expect(rows(html, "Dependencies")).not.toContain("data-field");
    expect(rows(html, "Dependencies")).toContain('<span class="id">TASK-1</span>');
  });
});

const at = (sec: number) => new Date(sec * 1000).toISOString();
const criterion = (over: Partial<StartCriterion>): StartCriterion => ({
  id: "rows", kind: "sql", expr: "select count(*) from runs", cmp: "equals", want: 3, status: "unmet", observed: 2, error: null, checked: at(700), ...over,
});
const criteria: StartCriterion[] = [
  criterion({ id: "soak-24h", kind: "prom", expr: "time()", cmp: "at_least", want: 1791400000, status: "unmet", observed: 1791336841 }),
  criterion({ id: "rows", status: "met", observed: 3 }),
  criterion({ id: "pin-moved", kind: "file_changed_since", expr: "starpulse", cmp: "since", want: "2026-10-05", status: "unmet", observed: 0 }),
  criterion({ id: "queue", kind: "prom", expr: "up", cmp: "at_least", want: 1, status: "not evaluated", observed: null, checked: null }),
  criterion({ id: "gate", kind: "sql", expr: "select 1", status: "error", observed: null, error: "criteria: exit 2: prometheus is down", checked: null }),
];
const sectionOf = (html: string, name: string) => {
  const rail = railOf(html);
  const from = rail.indexOf(`>${name}</span>`);
  return from < 0 ? "" : rail.slice(from, rail.indexOf("</section>", from));
};
const withCriteria = (list: StartCriterion[] | undefined) => draw({ record: { ...record, start_criteria: list } });

describe("the Start Criteria section", () => {
  it("draws each criterion's mark, kind, id, threshold and last value, with how long ago it was checked", () => {
    const html = sectionOf(withCriteria(criteria), "Start Criteria");

    expect(html).toContain("1/5 met");
    expect(html).toContain("○ unmet");
    expect(html).toContain("✓ met");
    for (const text of ["soak-24h", "prom", "rows", "sql", "select count(*) from runs", "equals 3 · last 3 · checked 5m ago", "since 2026-10-05 · last 0 · checked 5m ago"]) expect(html, text).toContain(text);
  });

  it("reads a time() criterion as when it opens, in Arizona time", () => {
    const html = sectionOf(withCriteria(criteria), "Start Criteria");

    expect(html).toContain("opens Oct 7, 12:06 MST · checked 5m ago");
    expect(html).not.toContain("at least 1791400000");
  });

  it("draws a criterion that was not evaluated with no mark and a muted note", () => {
    const card = sectionOf(withCriteria([criteria[3]]), "Start Criteria");

    expect(card).toContain("not evaluated");
    expect(card).not.toMatch(/[✓○]/);
    expect(card).toContain('class="c pending"');
    expect(card).toContain("at least 1");
  });

  it("draws an evaluator error as its message, with no mark", () => {
    const card = sectionOf(withCriteria([criteria[4]]), "Start Criteria");

    expect(card).toContain('class="c error"');
    expect(card).toContain("criteria: exit 2: prometheus is down");
    expect(card).not.toMatch(/[✓○]/);
    expect(card).not.toContain("last ");
  });

  it("sits in the right rail after Status and Session and is absent when the task has no criteria", () => {
    expect(headings(withCriteria(criteria)).slice(0, 3)).toEqual(["Status", "Session", "Start Criteria"]);
    expect(headings(withCriteria([]))).not.toContain("Start Criteria");
    expect(headings(withCriteria(undefined))).not.toContain("Start Criteria");
    expect(html(withCriteria(criteria)).left).not.toContain("Start Criteria</span>");
  });
});

const html = (markup: string) => ({ left: markup.slice(markup.indexOf('class="tvcol tvleft"'), markup.indexOf('class="tvcol tvrail"')) });
const yaml = "```yaml\nstart_criteria:\n- id: rows\n  kind: sql\n```";

describe("the description's start_criteria block", () => {
  it("gives way to a pointer to the section when the record carries the criteria", () => {
    const { left } = html(draw({ record: { ...record, description: `Wait.\n\n## Start Criteria\n\n${yaml}`, start_criteria: criteria } }));

    expect(left).toContain("<h4>Start Criteria</h4>");
    expect(left).toContain("Start Criteria are drawn in the side panel, each with its result");
    expect(left).not.toContain("start_criteria:");
  });

  it("keeps the raw block when there are no criteria to draw in its place", () => {
    const { left } = html(draw({ record: { ...record, description: `Wait.\n\n${yaml}` } }));

    expect(left).toContain("<pre>start_criteria:\n- id: rows\n  kind: sql</pre>");
  });
});

describe("the task view's Pull requests section carries each pull request's CI history", () => {
  const step = (event: string, state: string, at: number) => ({ event, state, at });
  const pull = (number: number) => ({ number, repo: "o/r", url: `http://pr/${number}`, checks: "pass" as const, merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false });
  const trail = [
    step("PR_OPENED", "opened", 1), step("PUSHED", "running", 2), step("CHECKS_FAILED", "failing", 3), step("RERUN", "running", 4), step("CHECKS_PASSED", "passing", 5),
    step("CONFLICTED", "conflicting", 6), step("REBASED", "running", 7), step("CHECKS_PASSED", "passing", 8), step("MERGED", "merged", 9),
    step("PR_OPENED", "opened", 10), step("PUSHED", "running", 11), step("CHECKS_FAILED", "failing", 12),
  ];
  const ci = (source: string | null = "GitHub") => [{ machine: "ci", state: "failing", at: 12, source, trail }];
  const section = (html: string) => railOf(html).split("<section").find((s) => s.includes('<span class="t">Pull requests</span>')) ?? "";
  const rowOf = (html: string, ref: string) => section(html).split('<div class="pull">').find((r) => r.includes(`${ref} ↗`)) ?? "";
  const two = { prs: [pull(15), pull(12)], machines: ci() };

  it("draws no CI history section, so each pull request is listed once", () => {
    const html = draw({ task: { ...task, ...two } });

    expect(railOf(html)).not.toContain("CI history");
    expect(railOf(html).split("o/r#12").length).toBe(2);
  });

  it("gives each pull request row its checks, its CI state and its four counts", () => {
    const html = draw({ task: { ...task, ...two } });
    const merged = rowOf(html, "o/r#12");
    const failing = rowOf(html, "o/r#15");

    expect(merged).toMatch(/merged[\s\S]*1 run[\s\S]*1 re-run[\s\S]*1 rebase[\s\S]*1 conflict/);
    expect(failing).toMatch(/checks pass[\s\S]*failing[\s\S]*1 run[\s\S]*0 re-runs[\s\S]*0 rebases[\s\S]*0 conflicts/);
  });

  it("totals the task's counts at the top of the section, only when there are two pull requests to total", () => {
    const one = { prs: [pull(12)], machines: [{ ...ci()[0], trail: trail.slice(0, 9) }] };
    const html = section(draw({ task: { ...task, ...two } }));

    expect(html).toContain('class="tot"');
    expect(html.indexOf('class="tot"')).toBeLessThan(html.indexOf("o/r#"));
    expect(html).toMatch(/class="tot"[\s\S]*2 runs[\s\S]*1 re-run[\s\S]*1 rebase[\s\S]*1 conflict/);
    expect(section(draw({ task: { ...task, ...one } }))).not.toContain('class="tot"');
    expect(rowOf(draw({ task: { ...task, ...one } }), "o/r#12")).toContain("merged");
  });

  it("draws the state in the mapped colour only when a third party moves the machine", () => {
    expect(section(draw({ task: { ...task, ...two } }))).toContain("mapped");
    expect(section(draw({ task: { ...task, prs: two.prs, machines: ci(null) } }))).not.toContain("mapped");
    expect(styles).toMatch(/#kbm \.tvrail \.ci \.st\.mapped[^{]*\{[^}]*var\(--mapped\)/);
  });

  it("draws a CI entry that matches no pull request as its own row", () => {
    const html = section(draw({ task: { ...task, prs: [], machines: ci() } }));

    expect(html).not.toContain("None yet");
    expect(html).toMatch(/pull request[\s\S]*1 run/);
  });

  it("says None yet with no pull request and no CI, and draws a pull request alone when no CI is recorded", () => {
    expect(section(draw({ task: { ...task, prs: [], machines: [] } }))).toContain("None yet");
    const html = section(draw({ task: { ...task, prs: [pull(12)], machines: [] } }));
    expect(html).toContain("o/r#12");
    expect(html).not.toContain("run");
  });
});

describe("opening the task view stays off the layout engine", () => {
  it("sizes its textareas in CSS, so a mount reads no scrollHeight and sets no height", () => {
    const read = vi.spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get").mockReturnValue(0);
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    act(() => root.render(<TaskView {...props()} />));
    const title = host.querySelector<HTMLTextAreaElement>('textarea[data-field="title"]')!;

    expect(read).not.toHaveBeenCalled();
    expect(title.style.height).toBe("");
    expect(styles).toMatch(/#kbm \.tv textarea\.fv:not\(\.long\)\s*\{[^}]*field-sizing:\s*content/);
    act(() => root.unmount());
    host.remove();
    read.mockRestore();
  });

  it("dims the board with a flat scrim: a backdrop blur makes every frame under it repaint the whole board", () => {
    const scrim = styles.match(/^#kbm \{[^}]*\}/m)![0];

    expect(scrim).toContain("background:");
    expect(scrim).not.toContain("backdrop-filter");
  });
});

describe("the Move to menu under a moving pointer", () => {
  it("commits nothing while the pointer moves within the row already lit, and lights the row it moves onto", () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.body.appendChild(document.createElement("div")), root = createRoot(host);
    let commits = 0;
    act(() => root.render(<Profiler id="tv" onRender={() => commits++}><TaskView {...props()} /></Profiler>));
    try {
      act(() => host.querySelector<HTMLButtonElement>('.mv button[aria-haspopup="menu"]')!.click());
      const rows = [...host.querySelectorAll<HTMLElement>('.mvmenu [role="menuitem"]')];
      const move = (row: HTMLElement) => act(() => void row.dispatchEvent(new MouseEvent("mousemove", { bubbles: true })));
      move(rows[0]);
      const before = commits;
      for (let i = 0; i < 5; i++) move(rows[0]);
      expect(commits).toBe(before);
      move(rows[1]);
      expect(rows[1].classList.contains("on")).toBe(true);
    } finally {
      act(() => root.unmount());
      host.remove();
    }
  });
});

describe("the task view's workflow runs", () => {
  it("links each run the task's id names, and draws no section for a task with none", () => {
    const runs = [{ url: "http://dagu/dag-runs/w/dag-run-task-7-1", status: "failed", startedAt: "2026-10-17T15:00:00Z" }];
    expect(draw({ task: { ...task, runs } })).toContain('href="http://dagu/dag-runs/w/dag-run-task-7-1"');
    expect(draw({ task })).not.toContain(">Runs<");
  });

  it("writes each run's start in Arizona time, and a dash for a start it cannot read", () => {
    const runs = [{ url: "#", status: "failed", startedAt: "2026-10-17T15:00:00Z" }, { url: "#", status: "running", startedAt: "" }];
    const html = draw({ task: { ...task, runs } });
    expect(html).toContain("Oct 17, 08:00 ↗");
    expect(html).toContain("— ↗");
  });
});

describe("the task view's Pull requests rail", () => {
  const pull = (number: number, over: Partial<Pull> = {}): Pull => ({ number, repo: "o/r", url: `http://pr/${number}`, checks: "pass", merged: false, merge_sha: null, merged_at: null, threads: 0, stale: false, ...over });
  const section = (html: string) => railOf(html).split('<section class="sec rs">').find((s) => s.includes(">Pull requests<")) ?? "";

  it("draws an unread citation as not read yet with its reason, never last read failed or checks none", () => {
    const html = section(draw({ task: { ...task, prs: [pull(7, { stale: true, checks: "none" })] } }));

    expect(html).toContain('<span class="chk unread"><i></i>not read yet</span>');
    expect(html).toContain('<span class="rd">no read since it was cited</span>');
    expect(html).not.toMatch(/last read failed|checks none/);
  });

  it("draws a read pull request's check result and its unread reviews", () => {
    const html = section(draw({ task: { ...task, prs: [pull(8, { checks: "failing", threads: 2 })] } }));

    expect(html).toContain('<span class="chk fail"><i></i>checks failing</span>');
    expect(html).toContain('<span class="rd">2 unread reviews</span>');
  });

  it("scrolls the list inside a box so the rail keeps every row visible", () => {
    expect(section(draw({ task: { ...task, prs: [pull(8)] } }))).toContain('class="box"');
  });
});
