// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Md, RepoBase } from "./Markdown";
import { CRITERIA_POINTER } from "./taskViewModel";

type Props = Partial<Parameters<typeof Md>[0]>;
const dom = (text: string, over: Props = {}, base: string | null = null) => {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<RepoBase.Provider value={base}><Md text={text} open={() => {}} {...over} /></RepoBase.Provider>);
  return host;
};
const texts = (host: Element, selector: string) => [...host.querySelectorAll(selector)].map((el) => el.textContent);

beforeEach(() => localStorage.clear());

describe("Md", () => {
  it("links each TASK-N id to its task and opens it in the dialog on a click", async () => {
    const open = vi.fn();
    const host = document.createElement("div");
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    await act(async () => createRoot(host).render(<Md text={"see TASK-12 and `TASK-13`"} open={open} />));
    const link = host.querySelector<HTMLAnchorElement>("a.tl")!;
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(click);

    expect(link.textContent).toBe("TASK-12");
    expect(link.getAttribute("href")).toBe("?view=kanban&task=TASK-12");
    expect(host.querySelectorAll("a.tl")).toHaveLength(1);
    expect(click.defaultPrevented).toBe(true);
    expect(open).toHaveBeenCalledWith("TASK-12");
  });

  it("draws a fence with its language, a pipe table with right-aligned cells and a list", () => {
    const host = dom("```yaml\na: <1>\n\nb: 2\n```\n\n| a | b |\n|:-- | --: |\n| 1 | 2 |\n\n1. step\n   - a\n   - b\n2. next");

    expect(texts(host, "figure.fence .lang")).toEqual(["yaml"]);
    expect(host.querySelector("figure.fence pre")?.textContent).toBe("a: <1>\n\nb: 2");
    expect(texts(host, ".tbl th")).toEqual(["a", "b"]);
    expect(texts(host, ".tbl td.r")).toEqual(["2"]);
    expect(host.querySelectorAll("ol > li > ul > li")).toHaveLength(2);
  });

  it("draws a `##` heading as an h4 and, with folds, as a section with a one-line preview when closed", () => {
    const text = "Lead\n\n## Outcome\n\nOpen **now**.\n\n## Notes\n\n- one `two`\n- three";
    const plain = dom(text);
    const folded = dom(text, { folds: true });

    expect(texts(plain, "h4")).toEqual(["Outcome", "Notes"]);
    expect(texts(folded, "details.dsec summary .ht")).toEqual(["Outcome", "Notes"]);
    expect(texts(folded, "details.dsec summary .pv")).toEqual(["Open now.", "one two · three"]);
    expect([...folded.querySelectorAll("details.dsec")].map((d) => d.hasAttribute("open"))).toEqual([true, false]);
    expect(folded.querySelector(".desc > div")?.textContent?.trim()).toBe("Lead");
  });

  it("replaces the start_criteria block with the pointer to the rail when drawn", () => {
    const text = "```yaml\nstart_criteria:\n  - a\n```\n\nafter";

    expect(dom(text, { drawn: true }).querySelector("p.moved")?.textContent).toBe(CRITERIA_POINTER);
    expect(dom(text).querySelector("p.moved")).toBeNull();
  });

  it("draws a mermaid fence as a diagram only with diagrams, and as code otherwise", () => {
    const text = "```mermaid\nflowchart LR\n  A --> B\n```";

    expect(dom(text, { diagrams: true }).textContent).toContain("Drawing diagram…");
    expect(texts(dom(text), "figure.fence .lang")).toEqual(["mermaid"]);
  });

  it("links a file path in code into the task's repository only when it has one", () => {
    const text = "edit `starpulse/web/src/a.ts` and `plain`";
    const linked = dom(text, {}, "https://github.com/o/r");
    const bare = dom(text);

    expect(linked.querySelector<HTMLAnchorElement>("code a.rp")?.getAttribute("href")).toBe("https://github.com/o/r/blob/main/starpulse/web/src/a.ts");
    expect(texts(linked, "code")).toEqual(["starpulse/web/src/a.ts", "plain"]);
    expect(bare.querySelector("a.rp")).toBeNull();
    expect(texts(bare, "code")).toEqual(["starpulse/web/src/a.ts", "plain"]);
  });

  it("opens an outside link in a new tab and draws emphasis, but strips script from the text's own HTML", () => {
    const host = dom("*soft* [docs](https://x.test/a) <img src=x onerror=alert(1)> [bad](javascript:alert(1)) <script>alert(2)</script>");
    const link = host.querySelector<HTMLAnchorElement>("a[target]")!;

    expect(host.querySelector("em")?.textContent).toBe("soft");
    expect([link.getAttribute("href"), link.getAttribute("target"), link.getAttribute("rel")]).toEqual(["https://x.test/a", "_blank", "noopener"]);
    expect(host.innerHTML).not.toMatch(/onerror|javascript:|<script/i);
  });
});
