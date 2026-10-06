// The click panel's content. The renderer owns when it opens; it floats over the level and never refits it.
import { apiFetch } from "./demo";
import { queryString } from "./nav";
import type { FanRow, QueueRow } from "./fan";
import type { Sky } from "./sky";
import type { RawAgent } from "./types";

export const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/** Start a run-safe DAG through the server's run endpoint: the line the panel shows once it answers. */
export async function startRun(dag: string, post: (url: string, init?: RequestInit) => Promise<Response> = apiFetch): Promise<string> {
  try {
    const resp = await post(`/api/run/${dag.split("/").map(encodeURIComponent).join("/")}`, { method: "POST" });
    const body = await resp.json();
    return resp.ok ? `Started run ${body.runId}.` : `Not started: ${body.error}`;
  } catch (e) {
    return `Not started: ${e instanceof Error ? e.message : String(e)}`;
  }
}

const link = (href: string, text: string) => `<a href="${esc(href)}" target="_blank" rel="noopener">${esc(text)}</a>`;

/** A task's link: the configured tracker's page, or with none this page's own Kanban, which opens on it. */
export function taskLink(id: string, text: string, sky: Sky, search = globalThis.location?.search ?? ""): string {
  const board = sky.boardUrl?.replace(/\/$/, "");
  if (board) return link(`${board}/tasks/${id}`, text);
  const params = new URLSearchParams(search);
  params.set("view", "kanban");
  params.set("task", id);
  return `<a href="${esc(queryString(params))}">${esc(text)}</a>`;
}

/** The panel of one Board task: where it stands, what it waits on, its pull requests and the machines it sits on; its description is the Kanban's. */
export function taskPanel(o: RawAgent, sky: Sky, stateName: (id: string) => string, search = globalThis.location?.search ?? ""): string {
  const onBoard = (id: string, text: string) => taskLink(id, text, sky, search);
  const machines = Object.values(sky.flows).filter((f) => f.name !== "board").flatMap((f) => f.agents.filter((s) => s.task === o.id).map((s) => `${esc(f.name)} · ${esc(s.state)}`));
  const deps = (o.dependencies ?? []).map((id) => onBoard(id, id));
  const prs = (o.prs ?? []).map((url) => link(url, `#${/(\d+)\/?$/.exec(url)?.[1] ?? url}`));
  return `<span class="x">✕</span><div class="k">task · click another dot or empty space to close</div><h2>${esc(o.id)} — ${esc(o.title)}</h2>
    <table><tr><td>Status</td><td>${esc(stateName(o.state))}</td></tr><tr><td>Profile</td><td>${esc(o.model)}</td></tr>
    <tr><td>Labels</td><td>${(o.labels ?? []).map((l) => `<span class="chip">${esc(l)}</span>`).join("")}</td></tr>
    <tr><td>Depends on</td><td>${deps.join(", ") || "none"}</td></tr><tr><td>Pull request</td><td>${prs.join(", ") || "none"}</td></tr>
    <tr><td>Machines</td><td>${machines.join("<br>") || "none"}</td></tr></table>
    <div class="note">${onBoard(o.id, "Open on board ↗")}</div>`;
}

/** Minutes and seconds of a duration. */
export const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** The Queue row's value: the pool's running count against its cap, this DAG's share when others share it, and a bar. */
export function queueCell(q: QueueRow): string {
  const state = q.full ? "full" : "";
  return `${esc(q.pool)} · <b class="qn ${state}">${q.running}</b> of ${q.cap} running${q.mine !== q.running ? ` (${q.mine} of them this DAG)` : ""}${q.queued ? ` · ${q.queued} queued` : ""}
    <div class="qbar"><i class="${state}" style="width:${q.cap ? Math.min(100, (q.running / q.cap) * 100) : 0}%"></i></div>`;
}

const fanRow = (r: FanRow, taskHref: (task: string) => string) => {
  const strip = r.strip.map((s) => `<i class="${r.state === "queued" || s.status === "not_started" ? "" : s.status}" title="${esc(s.name)}"></i>`).join("");
  const failedAt = r.strip.find((s) => s.status === "failed")?.name ?? r.step;
  const what =
    r.state === "queued" ? "queued for a slot"
    : r.state === "failed" ? `<b class="bad">failed at ${esc(failedAt)}</b>`
    : r.state === "succeeded" ? `<b class="ok">succeeded</b>`
    : r.step ? `<b>${esc(r.step)}</b> · ${mmss(r.inStep)} in step` : "<b>between steps</b>";
  return `<div class="fr${r.flash ? " adv" : ""}${r.state === "queued" ? " queued" : ""}" title="${esc(r.id)}">${r.task ? taskHref(r.task) : `<span class="rid">${esc(r.id.slice(0, 12))}</span>`}<div class="strip">${strip}</div><div class="el">${r.state === "queued" ? "—" : mmss(r.elapsed)}</div><div class="st">${what}</div></div>`;
};

/** The In-flight list: one row per run, longest-running first, the queued runs after; with none, when the last run ended (`last` is already escaped). */
export function fanList(rows: FanRow[], last: string, taskHref: (task: string) => string): string {
  const running = rows.filter((r) => r.state !== "queued"), waiting = rows.length - running.length;
  return `<div class="hd"><span>In flight · ${rows.filter((r) => r.state === "running").length}${waiting ? ` + ${waiting} queued` : ""}</span><span>elapsed</span></div>
    ${rows.length ? rows.map((r) => fanRow(r, taskHref)).join("") : `<div class="empty">No run in flight. Last run ${last}.</div>`}`;
}
