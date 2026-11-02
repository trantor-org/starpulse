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
const drawCard = (readable: string) => renderToStaticMarkup(
  <Card task={card("TASK-5", "ready", { readable })} now={160} marks={{}} names={{}} roles={LIFECYCLE_ROLES} onOpen={() => {}} dismiss={() => {}} compact={false} />,
);
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

    expect(html).toContain("<ol><li>step<ul><li>a <code>b</code></li><li>c</li></ul></li></ol>");
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
  it("draws no badge, find box or expand/collapse-all control, even for a failing verdict", () => {
    const html = draw({ task: { ...task, readable: "Outcome is missing" }, record: { ...record, description } });

    expect(html).not.toContain("legacy format");
    expect(html).not.toContain('class="legacy"');
    expect(html).not.toMatch(/type="search"|role="search"/);
    expect(html).not.toMatch(/expand all|collapse all/i);
  });
});

describe("a board card's badge", () => {
  it("draws the legacy-format badge, carrying the verdict, for a failing readable verdict", () => {
    const html = drawCard("the description has no Outcome heading");

    expect(html).toContain('<span class="legacy" title="the description has no Outcome heading">legacy format</span>');
  });

  it("draws no badge when the description reads well", () => {
    expect(drawCard("")).not.toContain("legacy");
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
