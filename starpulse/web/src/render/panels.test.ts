import { describe, expect, it } from "vitest";
import type { FanRow, QueueRow } from "../features/fanout/fan";
import { fanList, queueCell, startRun, taskPanel } from "./panels";
import { merge } from "./sky";
import type { RawAgent, Snapshot } from "../api";

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
const panel = (o: RawAgent, boardUrl?: string | null, search = "") => taskPanel(o, sky([o], boardUrl), (id) => (id === "in_progress" ? "In Progress" : id), search);

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

  it("opens the task and its dependencies in the page's own Kanban when there is no tracker", () => {
    const html = panel(task({ dependencies: ["PROJ-2156"] }), null);

    expect(html).toContain('<a href="?view=kanban&amp;task=PROJ-2156">PROJ-2156</a>');
    expect(html).toContain('<a href="?view=kanban&amp;task=PROJ-7">Open on board ↗</a>');
  });

  it("keeps the page's other parameters on its Kanban link", () => {
    expect(panel(task(), null, "?demo&view=constellation")).toContain('<a href="?demo&amp;view=kanban&amp;task=PROJ-7">Open on board ↗</a>');
  });

  it("opens the task on the tracker when one is configured", () => {
    expect(panel(task())).toContain('<a href="http://board/tasks/PROJ-7" target="_blank" rel="noopener">Open on board ↗</a>');
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

describe("the DAG panel's queue and runs", () => {
  const q = (o: Partial<QueueRow> = {}): QueueRow => ({ pool: "deliver", running: 5, cap: 32, queued: 0, mine: 5, full: false, ...o });
  const row = (o: Partial<FanRow> = {}): FanRow => ({ id: "deliver-agent-task-2787-x", task: "TASK-2787", state: "running", strip: [{ name: "lint", status: "running" }], step: "lint", inStep: 65, elapsed: 125, flash: false, ...o });
  const href = (id: string) => `<a>${id}</a>`;

  it("names the pool's running count against its cap, and this DAG's share only when other DAGs hold slots", () => {
    expect(queueCell(q())).toContain("deliver · <b class=\"qn \">5</b> of 32 running");
    expect(queueCell(q())).not.toContain("this DAG");
    expect(queueCell(q({ pool: "default", running: 2, cap: 2, mine: 1, queued: 1, full: true }))).toContain("<b class=\"qn full\">2</b> of 2 running (1 of them this DAG) · 1 queued");
  });

  it("says when the last run ended when nothing is in flight", () => {
    expect(fanList([], "succeeded 16:04 MST", href)).toContain("No run in flight. Last run succeeded 16:04 MST.");
  });

  it("draws a running row with its step and time in it, and a failed row with the step it failed at", () => {
    const failed = row({ state: "failed", strip: [{ name: "lint", status: "failed" }], step: "" });

    expect(fanList([row()], "", href)).toContain("<b>lint</b> · 1:05 in step");
    expect(fanList([failed], "", href)).toContain('<b class="bad">failed at lint</b>');
    expect(fanList([row(), row({ id: "q", task: null, state: "queued" })], "", href)).toContain("In flight · 1 + 1 queued");
  });
});
