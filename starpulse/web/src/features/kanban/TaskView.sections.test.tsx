// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it } from "vitest";
import description from "./fixtures/task-9251.md?raw";
import { Card } from "./Kanban";
import { SECTIONS_KEY } from "./Markdown";
import { TaskView } from "./TaskView";
import { LIFECYCLE_ROLES } from "../../tests/lifecycleRoles";
import { card, props, record, task } from "../../tests/taskViewFixtures";

const draw = (over: Partial<Parameters<typeof TaskView>[0]> = {}) => renderToStaticMarkup(<TaskView {...props(over)} />);
const sectionOf = (html: string, name: string) => new RegExp(`<details[^>]*data-section="${name}"[^>]*>`).exec(html)?.[0] ?? "";

beforeEach(() => localStorage.clear());

describe("the task dialog's description", () => {
  it("draws TASK-9251's lists and inline code as <ol>, <ul> and <code>", () => {
    const html = draw({ record: { ...record, description } });

    expect(html).toContain("<ul>");
    expect(html).toContain("<ol>");
    expect(html).toContain("<code>pulls/model/</code>");
  });

  it("draws a nested list inside its item", () => {
    const html = draw({ record: { ...record, description: "## Scope\n\n1. step\n   - a `b`\n   - c" } });

    expect(html.replace(/\s*\n\s*/g, "")).toContain("<ol><li>step<ul><li>a <code>b</code></li><li>c</li></ul></li></ol>");
  });

  it("caps the pane and makes each heading a toggle, with Outcome, Why and Scope open and the rest closed", () => {
    const html = draw({ record: { ...record, description } });

    expect(html).toContain('class="md desc"');
    expect(sectionOf(html, "Why This Matters")).toContain(" open");
    expect(sectionOf(html, "Scope")).toContain(" open");
    expect(sectionOf(html, "Constraints")).not.toContain(" open");
    expect(sectionOf(html, "Implementation Plan")).not.toBe("");
    expect(html).toMatch(/<summary><span class="car"><\/span><span class="ht">Constraints<\/span><span class="pv">[^<]+<\/span><\/summary>/);
  });

  it("opens the sections the browser last stored by heading name", () => {
    localStorage.setItem(SECTIONS_KEY, JSON.stringify({ Scope: false, Constraints: true }));
    const html = draw({ record: { ...record, description } });

    expect(sectionOf(html, "Scope")).not.toContain(" open");
    expect(sectionOf(html, "Constraints")).toContain(" open");
  });

  it("starts from the defaults when the stored state is unreadable", () => {
    localStorage.setItem(SECTIONS_KEY, "{not json");

    expect(sectionOf(draw({ record: { ...record, description } }), "Scope")).toContain(" open");
  });

  it("draws no Definition of done section", () => {
    const html = draw({ record: { ...record, definitionOfDone: [{ n: 1, text: "The completing-tasks skill was invoked", checked: false }] } });

    expect(html).not.toContain("Definition of done");
    expect(html).not.toContain("The completing-tasks skill was invoked");
  });
});

describe("the dialog's controls", () => {
  it("draws no find box or expand/collapse-all control", () => {
    const html = draw({ record: { ...record, description } });

    expect(html).not.toMatch(/type="search"|role="search"/);
    expect(html).not.toMatch(/expand all|collapse all/i);
  });
});

describe("a board card's actor-error chip", () => {
  const faulted = "## Description\n\nWork.\n\n## Needs attention\n\nTask actor fault: fact pr_failing: the comments are unreadable\n\nFix it?";
  const drawFault = (text: string) => renderToStaticMarkup(
    <Card task={card("TASK-5", "needs_attention", { description: text })} now={160} marks={{}} names={{}} roles={LIFECYCLE_ROLES} onOpen={() => {}} dismiss={() => {}} compact={false} />,
  );

  it("carries the fault as its title when the Needs attention reason opens with one", () => {
    expect(drawFault(faulted)).toContain('<span class="fault" title="Task actor fault: fact pr_failing: the comments are unreadable">actor error</span>');
  });

  it("is absent for an ordinary reason or a fault named further down", () => {
    expect(drawFault("## Needs attention\n\nFix it?\n\nTask actor fault: x")).not.toContain("actor error");
    expect(drawFault("Task actor fault: x")).not.toContain("actor error");
  });

  it("leaves an ordinary ask off the card", () => {
    expect(drawFault("## Needs attention\n\nWhich one?")).not.toContain('class="ask"');
  });
});

describe("the dialog's Needs attention section", () => {
  it("starts closed while Outcome, Why and Scope start open", () => {
    const html = draw({ record: { ...record, description: "## Outcome\n\nO\n\n## Why\n\nW\n\n## Scope\n\nS\n\n## Needs attention\n\nWhich one?" } });

    expect(["Outcome", "Why", "Scope"].map((n) => sectionOf(html, n))).toSatisfy((a: string[]) => a.every((t) => t.includes(" open")));
    expect(sectionOf(html, "Needs attention")).not.toContain(" open");
  });
});

describe("the plan heading", () => {
  it("shows revised N× linking the Activity section once the plan was rewritten", () => {
    const html = draw({ revisions: 2 });

    expect(html).toContain('<a class="rev" href="#activity">revised 2×</a>');
  });

  it("shows nothing for a plan never revised", () => {
    expect(draw({ revisions: 0 })).not.toContain("revised");
  });
});

describe("repo paths in the description", () => {
  const pull = { ...task.prs[0], url: "https://github.com/trantor-org/starpulse/pull/1152" };

  it("draws a file path repo-relative and linked to the file on the task's repository", () => {
    const html = draw({ task: { ...task, prs: [pull] }, record: { ...record, description: "## Scope\n\n- edit `/home/adinb/trantor/starpulse/web/src/style.css`" } });

    expect(html).toContain('<code><a class="rp" href="https://github.com/trantor-org/starpulse/blob/main/starpulse/web/src/style.css" target="_blank" rel="noopener">starpulse/web/src/style.css</a></code>');
  });

  it("draws the path unlinked when the task has no pull request to name the repository", () => {
    const html = draw({ task: { ...task, prs: [] }, record: { ...record, description: "## Scope\n\n- edit `starpulse/web/src/style.css`" } });

    expect(html).toContain("<code>starpulse/web/src/style.css</code>");
  });
});
