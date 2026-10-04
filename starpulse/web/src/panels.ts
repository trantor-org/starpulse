// The click panel's content. The renderer owns when it opens; it floats over the level and never refits it.
import type { Sky } from "./sky";
import type { RawAgent } from "./types";

export const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/** Start a run-safe DAG through the server's run endpoint: the line the panel shows once it answers. */
export async function startRun(dag: string, post: (url: string, init?: RequestInit) => Promise<Response> = fetch): Promise<string> {
  try {
    const resp = await post(`/api/run/${dag.split("/").map(encodeURIComponent).join("/")}`, { method: "POST" });
    const body = await resp.json();
    return resp.ok ? `Started run ${body.runId}.` : `Not started: ${body.error}`;
  } catch (e) {
    return `Not started: ${e instanceof Error ? e.message : String(e)}`;
  }
}

const link = (href: string, text: string) => `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`;

/** The panel of one Board task: where it stands, what it waits on, its pull requests and the machines it sits on; its description is the Kanban's. */
export function taskPanel(o: RawAgent, sky: Sky, stateName: (id: string) => string): string {
  const board = sky.boardUrl?.replace(/\/$/, "");
  const machines = Object.values(sky.flows).filter((f) => f.name !== "board").flatMap((f) => f.agents.filter((s) => s.task === o.id).map((s) => `${esc(f.name)} · ${esc(s.state)}`));
  const deps = (o.dependencies ?? []).map((id) => (board ? link(`${board}/tasks/${id}`, id) : esc(id)));
  const prs = (o.prs ?? []).map((url) => link(url, `#${/(\d+)\/?$/.exec(url)?.[1] ?? url}`));
  return `<span class="x">✕</span><div class="k">task · click another dot or empty space to close</div><h2>${esc(o.id)} — ${esc(o.title)}</h2>
    <table><tr><td>Status</td><td>${esc(stateName(o.state))}</td></tr><tr><td>Profile</td><td>${esc(o.model)}</td></tr>
    <tr><td>Labels</td><td>${(o.labels ?? []).map((l) => `<span class="chip">${esc(l)}</span>`).join("")}</td></tr>
    <tr><td>Depends on</td><td>${deps.join(", ") || "none"}</td></tr><tr><td>Pull request</td><td>${prs.join(", ") || "none"}</td></tr>
    <tr><td>Machines</td><td>${machines.join("<br>") || "none"}</td></tr></table>
    <div class="note">${board ? link(`${board}/tasks/${o.id}`, "Open on board ↗") : ""}</div>`;
}
