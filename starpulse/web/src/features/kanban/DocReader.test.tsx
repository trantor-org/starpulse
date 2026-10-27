// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";
import { props, record } from "../../tests/taskViewFixtures";

const render = vi.fn(async (id: string) => ({ svg: `<svg data-id="${id}"></svg>` }));
vi.mock("mermaid", () => ({ default: { initialize: vi.fn(), render } }));

const bodies: Record<string, string> = {
  "doc-993": "# Task dialog redesign\n\n## Decisions\n\nD9 opens **docs** via `Md`.\n\n```mermaid\nflowchart LR\n  A --> B\n```",
  "doc-12": "## Notes\n\nPlain notes.",
};
const served: Record<string, unknown> = {
  "/api/milestones/m-89": { milestone: { id: "m-89", title: "Task dialog", description: "## Goal\n\nOne dialog.", specs: ["doc-993 — Task dialog redesign"] } },
  "/api/docs": { docs: [{ id: "doc-993", title: "Task dialog redesign", type: "specification" }, { id: "doc-12", title: "Working notes", type: "other" }] },
  "/api/docs/doc-993": { doc: { id: "doc-993", title: "Task dialog redesign", type: "specification", body: bodies["doc-993"] } },
  "/api/docs/doc-12": { doc: { id: "doc-12", title: "Working notes", type: "other", body: bodies["doc-12"] } },
};

describe("the task view's Docs", () => {
  const mounted: { root: ReturnType<typeof createRoot>; host: HTMLElement }[] = [];
  const mount = async (over: Partial<Parameters<typeof TaskView>[0]> = {}) => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (
      url in served ? new Response(JSON.stringify(served[url]), { status: 200 }) : new Response("{}", { status: 404 })
    )));
    const host = document.body.appendChild(document.createElement("div"));
    const root = createRoot(host);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    await act(async () => root.render(<TaskView {...props({ record: { ...record, documentation: ["docs/specs/doc-993 - Task dialog redesign.md", "docs/doc-12 - Working notes.md"] }, ...over })} />));
    mounted.push({ root, host });
    return host;
  };
  afterEach(() => {
    for (const { root, host } of mounted.splice(0)) { act(() => root.unmount()); host.remove(); }
    vi.unstubAllGlobals();
    render.mockClear();
  });
  const rows = (host: HTMLElement) => [...host.querySelectorAll<HTMLAnchorElement>(".tvrail .doc")];
  const press = async (el: Element) => { await act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); }); };

  it("lists the milestone, its spec and the linked doc in the rail", async () => {
    const host = await mount();
    expect(rows(host).map((r) => [r.querySelector(".kd")?.textContent, r.querySelector(".tt")?.textContent])).toEqual([
      ["Milestone", "m-89Task dialog"],
      ["Spec", "doc-993Task dialog redesign"],
      ["Doc", "doc-12Working notes"],
    ]);
  });

  it("opens a spec in the dialog with its mermaid fence drawn, and Back to task restores the task", async () => {
    const host = await mount();
    await press(rows(host)[1]!);

    expect(host.querySelector(".docbar button")?.textContent).toContain("Back to task");
    expect(host.querySelector(".doctitle")?.textContent).toBe("Task dialog redesign");
    expect(host.querySelector(".tvleft h4")?.textContent).toBe("Decisions");
    expect(host.querySelector(".tvleft")?.textContent).not.toContain("# Task dialog redesign"); // the title bar already names it
    expect(host.querySelector(".tvleft strong")?.textContent).toBe("docs");
    expect(host.querySelector(".tvleft code")?.textContent).toBe("Md");
    expect(host.querySelector(".tvleft .mmd svg")).not.toBeNull();
    expect(render).toHaveBeenCalledWith(expect.stringMatching(/^mmd-/), "flowchart LR\n  A --> B");
    expect(rows(host)[1]!.getAttribute("aria-current")).toBe("true");

    await press(host.querySelector(".docbar button")!);
    expect(host.querySelector(".docbar")).toBeNull();
    expect(host.querySelector(".tvleft")?.textContent).toContain("Description");
  });

  it("reads the milestone's own description, and loads no mermaid for a doc without a diagram", async () => {
    const host = await mount();
    await press(rows(host)[0]!);
    expect(host.querySelector(".tvleft h4")?.textContent).toBe("Goal");
    await press(host.querySelector(".docbar button")!);
    await press(rows(host)[2]!);
    expect(host.querySelector(".tvleft h4")?.textContent).toBe("Notes");
    expect(render).not.toHaveBeenCalled();
  });

  it("shows no Docs row for a task with no milestone and no linked doc", async () => {
    const host = await mount({ record: { ...record, milestone: "", documentation: [] } });
    expect(rows(host)).toEqual([]);
    expect(host.textContent).not.toContain("Docs");
  });

  it("keeps a linked file the board does not serve as a row that does not open", async () => {
    const host = await mount({ record: { ...record, milestone: "", documentation: ["docs/doc-404 - Gone.md"] } });
    const [row] = rows(host);
    expect(row?.textContent).toBe("Docdoc-404Gone");
    expect(row?.getAttribute("href")).toBeNull();
  });
});
