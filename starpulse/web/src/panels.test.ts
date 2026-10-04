import { describe, expect, it } from "vitest";
import { startRun, taskPanel } from "./panels";
import { merge } from "./sky";
import type { RawAgent, Snapshot } from "./types";

const task = (extra: Partial<RawAgent> = {}): RawAgent => ({
  id: "PROJ-7", title: "Draw <flows>", state: "in_progress", model: "@agent-standard-high", labels: ["size-3"], description: "Draw the flow.", ...extra,
});
const sky = (tasks: RawAgent[], boardUrl: string | null = "http://board/") =>
  merge({
    graphs: ["board"],
    flows: [{ name: "board", agents: tasks, machine: { states: [{ id: "in_progress", name: "In Progress", initial: true, final: false }], transitions: [] } }],
    dags: [],
    boardUrl,
    settled: {},
    error: null,
    now: 0,
  } as Snapshot);
const panel = (o: RawAgent, boardUrl?: string | null) => taskPanel(o, sky([o], boardUrl), (id) => (id === "in_progress" ? "In Progress" : id));

describe("the task panel", () => {
  it("shows the task's state, profile and labels, and leaves its description to the Kanban", () => {
    const html = panel(task());

    expect(html).toContain("PROJ-7 — Draw &lt;flows&gt;");
    expect(html).toContain("<td>Status</td><td>In Progress</td>");
    expect(html).toContain("@agent-standard-high");
    expect(html).toContain('<span class="chip">size-3</span>');
    expect(html).not.toContain("Draw the flow.");
    expect(html).not.toContain('class="desc"');
  });

  it("links each dependency to its page on the board", () => {
    const html = panel(task({ dependencies: ["PROJ-2156", "PROJ-2157"] }));

    expect(html).toContain('<a href="http://board/tasks/PROJ-2156" target="_blank" rel="noopener">PROJ-2156</a>');
    expect(html).toContain('<a href="http://board/tasks/PROJ-2157" target="_blank" rel="noopener">PROJ-2157</a>');
  });

  it("names a dependency without a link when the page has no board address", () => {
    const html = panel(task({ dependencies: ["PROJ-2156"] }), null);

    expect(html).toContain("<td>Depends on</td><td>PROJ-2156</td>");
  });

  it("links each pull request by its number", () => {
    const html = panel(task({ prs: ["https://github.com/acme/widgets/pull/1750", "https://github.com/acme/widgets/pull/1751/"] }));

    expect(html).toContain('<a href="https://github.com/acme/widgets/pull/1750" target="_blank" rel="noopener">#1750</a>');
    expect(html).toContain('<a href="https://github.com/acme/widgets/pull/1751/" target="_blank" rel="noopener">#1751</a>');
  });

  it("says so when the task has no dependencies or pull request", () => {
    const html = panel(task());

    expect(html).toContain("<td>Depends on</td><td>none</td>");
    expect(html).toContain("<td>Pull request</td><td>none</td>");
  });
});

describe("Run now", () => {
  const answer = (status: number, body: unknown) => async () => new Response(JSON.stringify(body), { status });

  it("POSTs the DAG to the run endpoint and reports the run id Dagu gave it", async () => {
    const sent: [string, RequestInit | undefined][] = [];
    const post = async (url: string, init?: RequestInit) => (sent.push([url, init]), new Response('{"runId":"run-7"}'));

    expect(await startRun("whole-repo-gate", post)).toBe("Started run run-7.");
    expect(sent).toEqual([["/api/run/whole-repo-gate", { method: "POST" }]]);
  });

  it("keeps the instance and the workflow as two path segments, each encoded on its own", async () => {
    const sent: string[] = [];
    const post = async (url: string) => (sent.push(url), new Response('{"runId":"run-8"}'));

    await startRun("ci/nightly run", post);

    expect(sent).toEqual(["/api/run/ci/nightly%20run"]);
  });

  it("reports the server's refusal", async () => {
    expect(await startRun("whole-repo-gate", answer(502, { error: "Dagu refused the start (HTTP 409)" }))).toBe("Not started: Dagu refused the start (HTTP 409)");
  });

  it("reports a server it cannot reach", async () => {
    expect(await startRun("whole-repo-gate", async () => Promise.reject(new TypeError("Failed to fetch")))).toBe("Not started: Failed to fetch");
  });
});
