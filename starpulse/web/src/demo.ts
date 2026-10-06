// The demo: `?demo` walks random legal transitions in random flows so every section moves, and a self-contained
// demo page (`starpulse.demo`) runs that walk inside a DemoServer that answers the page's /api requests itself.
import type { LaneStep } from "./trace";
import type { Machine, RawAgent, Snapshot } from "./types";
import type { TaskRecord } from "./taskView";

let demoN = 0;

export function demoStep(prev: Snapshot, random = Math.random): Snapshot {
  const snap = structuredClone(prev);
  const f = snap.flows[Math.floor(random() * snap.flows.length)];
  if (!f) return stepDags(snap, random);
  const trans = f.machine.transitions;
  const init = f.machine.states.find((s) => s.initial)?.id ?? f.machine.states[0].id;
  const finals = new Set(f.machine.states.filter((s) => s.final).map((s) => s.id));
  const now = Date.now() / 1000;
  if (f.name === "board") {
    const pool = f.agents.filter((a) => a.state !== "done" || random() < 0.1);
    const ag = pool[Math.floor(random() * f.agents.length * 0.9)] ?? f.agents[0];
    const outs = ag ? trans.filter((e) => e.source === ag.state && e.target !== e.source) : [];
    if (ag && outs.length) {
      const e = outs[Math.floor(random() * outs.length)];
      if (finals.has(e.target)) {
        f.agents = f.agents.filter((a) => a !== ag);
        snap.settled[ag.id] = e.target;
      } else ag.state = e.target;
    }
  } else {
    if (!f.agents.length || (f.agents.length < 6 && random() < 0.25))
      f.agents.push({
        id: `DEMO-${100 + ++demoN}`, task: `DEMO-${100 + demoN}`, title: "demo", model: ["@agent-deep-high", "@agent-standard-high", ""][demoN % 3],
        state: init, steps: 0, trail: [], active: now,
      });
    const ag = f.agents[Math.floor(random() * f.agents.length)];
    const outs = trans.filter((e) => e.source === ag.state);
    if (outs.length && !finals.has(ag.state)) {
      const e = outs[Math.floor(random() * outs.length)];
      ag.state = e.target;
      ag.steps = (ag.steps ?? 0) + 1;
      (ag.trail ??= []).push({ state: e.target, event: e.event, at: now });
      ag.active = now;
    } else f.agents = f.agents.filter((a) => a !== ag);
  }
  return stepDags(snap, random);
}

function stepDags(snap: Snapshot, random: () => number): Snapshot {
  if (snap.dags.length && random() < 0.3) {
    const d = snap.dags[Math.floor(random() * snap.dags.length)];
    d.status = d.status === "running" ? (random() < 0.85 ? "succeeded" : "failed") : d.status === "queued" ? "running" : "queued";
    if (d.status === "queued") d.runId += "+";
  }
  return snap;
}

/** The snapshot `starpulse.demo` embeds, with each Board task's lane changes as `/api/history?task=` answers them. */
export type DemoFixture = Snapshot & { history?: Record<string, LaneStep[]> };

type Handler = (server: DemoServer, path: string, query: URLSearchParams, init?: RequestInit) => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const HANDLERS: Record<string, Handler> = {
  "/api/history": (server, _path, query) => {
    const task = query.get("task") ?? "", flow = query.get("flow");
    if (!flow) return json({ task, path: server.lanes[task] ?? [] });
    const f = server.snapshot.flows.find((x) => x.name === flow);
    if (!f) return json({ error: `no machine ${flow}` }, 404);
    const a = f.agents.find((x) => (x.task ?? x.id) === task);
    const path = (a?.trail ?? []).map(({ at, event, state }) => ({ at, event, state }));
    return json({ task, flow, path, steps: a ? (a.steps ?? path.length) : 0 });
  },
  "/api/move": async (server, _path, _query, init) => {
    const { task, to } = JSON.parse(String(init?.body ?? "{}")) as { task?: string; to?: string };
    return server.move(String(task), String(to));
  },
  "/api/task": (server, path) => server.task(decodeURIComponent(path.slice("/api/task/".length))),
  "/api/edit": (server, _path, _query, init) => server.edit(String(init?.body ?? "{}")),
};

/**
 * Every /api route the page requests, and how a demo page answers it: `null` for one the demo serves (`/api/events` by
 * `openStream` following the server, the rest by `DemoServer.fetch`), else why a page with no server cannot.
 * The demo test fails when the page's source requests a route missing here.
 */
export const ROUTES: Record<string, string | null> = {
  "/api/events": null,
  ...Object.fromEntries(Object.keys(HANDLERS).map((r) => [r, null])),
  "/api/run": "This demo has no runs instance to start a run on.",
  "/api/start": "This demo has no session-start service to start a session with.",
  // unanswered, the start question offers only Work it manually
  "/api/harnesses": "This demo has no harnesses configured.",
  "/api/history-window": "This demo has no server to keep a shared history window.",
};

/** The Board columns a card in `state` may be moved to: the machine's exits that are neither its creation nor a settled state. */
function columns(m: Machine, state: string): string[] {
  const rest = new Set(m.states.filter((s) => !s.initial && !s.final).map((s) => s.id));
  return [...new Set(m.transitions.filter((t) => t.source === state && t.target !== state && rest.has(t.target)).map((t) => t.target))];
}
const ALLOWED = { allowed: true, reason: "", skill: "" };

/**
 * The server a demo page has instead of starpulse.server: it holds the snapshot, plays the `?demo` walk on it, keeps
 * each Board card's lane history and move verdicts current, and answers /api requests from that, so every view and
 * every hover of a page with no server behaves as it does on a served one.
 */
export class DemoServer {
  snapshot: Snapshot;
  lanes: Record<string, LaneStep[]>;
  records: Record<string, TaskRecord>;
  private listeners = new Set<(s: Snapshot) => void>();
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(fixture: DemoFixture, private clock: () => number = () => Date.now() / 1000, private refuseEdits = false) {
    const { history, ...snap } = structuredClone(fixture);
    this.lanes = history ?? {};
    this.records = Object.fromEntries((snap.flows.find((f) => f.name === "board")?.agents ?? []).map((card) => [card.id, demoRecord(card)]));
    this.snapshot = this.verdicts({ ...snap, capabilities: { edit: true, archive: false } });
  }

  subscribe(fn: (s: Snapshot) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** Play the walk until `stop`, one step every 0.6 to 1.8 seconds. */
  start() {
    const tick = () => {
      this.step();
      this.timer = setTimeout(tick, 600 + Math.random() * 1200);
    };
    this.timer ??= setTimeout(tick, 1200);
  }
  stop() {
    clearTimeout(this.timer);
    this.timer = undefined;
  }

  /** One step of the walk, its Board lane changes recorded; a card it settles comes back as new work so the Board never drains. */
  step(random = Math.random) {
    const next = demoStep(this.snapshot, random);
    const board = next.flows.find((f) => f.name === "board");
    const prev = this.snapshot.flows.find((f) => f.name === "board")?.agents ?? [];
    const fresh = new Set<string>();
    if (board) {
      const lane = board.machine.mainLine?.[1] ?? board.machine.states.find((s) => s.initial)?.id ?? board.machine.states[0].id;
      for (const card of prev.filter((a) => a.id in next.settled)) {
        delete next.settled[card.id];
        delete this.lanes[card.id];
        fresh.add(card.id);
        board.agents.push({ ...card, state: lane, moves: undefined });
      }
    }
    this.publish(next, fresh);
  }

  /** Move `task` to column `to` as the board writer would: refused unless its lane exits there. */
  move(task: string, to: string): Response {
    const board = this.snapshot.flows.find((f) => f.name === "board");
    const card = board?.agents.find((a) => a.id === task);
    if (!board || !card) return json({ error: `${task} is not on the board` }, 404);
    if (!columns(board.machine, card.state).includes(to)) return json({ error: `${task} cannot move from ${card.state} to ${to}` }, 409);
    const next = structuredClone(this.snapshot);
    next.flows.find((f) => f.name === "board")!.agents.find((a) => a.id === task)!.state = to;
    this.publish(next);
    return json({ task, to });
  }

  /** The synthetic full record behind a public demo card. */
  task(id: string): Response {
    const record = this.records[id];
    return record ? json({ task: id, record }) : json({ error: `${id} has no record to read` }, 404);
  }

  /** Apply the same optimistic-lock payload as the served writer, then publish card-sized fields. */
  edit(raw: string): Response {
    let request: { task?: string; base?: Partial<TaskRecord>; changes?: Partial<TaskRecord> };
    try { request = JSON.parse(raw) as typeof request; } catch { return json({ error: "invalid edit" }, 400); }
    const task = request.task ?? "", current = this.records[task];
    if (!current || !request.base || !request.changes || !Object.keys(request.changes).length) return json({ error: "invalid edit" }, 400);
    if (this.refuseEdits) return json({ error: "The demo writer refused this edit.", skill: "completing-tasks" }, 409);
    const fields = Object.keys(request.changes) as (keyof TaskRecord)[];
    const stale = fields.filter((field) => JSON.stringify(current[field]) !== JSON.stringify(request.base?.[field]));
    if (stale.length) return json({ error: `${task} changed since it was opened: ${stale.join(", ")}`, stale, current: Object.fromEntries(stale.map((field) => [field, current[field]])) }, 409);
    this.records[task] = { ...current, ...request.changes } as TaskRecord;
    const next = structuredClone(this.snapshot);
    const card = next.flows.find((f) => f.name === "board")?.agents.find((agent) => agent.id === task);
    if (card) {
      const record = this.records[task];
      Object.assign(card, { title: record.title, model: record.profile, labels: record.labels, milestone: record.milestone, dependencies: record.dependencies, description: record.description });
      this.publish(next);
    }
    return json({ task, changed: fields });
  }

  fetch(input: string, init?: RequestInit): Promise<Response> {
    const [path, search = ""] = input.split("?", 2); // no URL(): a base address would be a host in the public file
    const route = Object.keys(ROUTES).find((r) => path === r || path.startsWith(`${r}/`));
    const handler = route ? HANDLERS[route] : undefined;
    if (handler) return Promise.resolve(handler(this, path, new URLSearchParams(search), init));
    return Promise.resolve(json({ error: (route && ROUTES[route]) || `This demo does not serve ${path}.` }, 404));
  }

  /** Push `next`, recording each Board lane change; a `fresh` card's path starts again from nothing. */
  private publish(next: Snapshot, fresh = new Set<string>()) {
    const was = new Map(this.snapshot.flows.find((f) => f.name === "board")?.agents.map((a) => [a.id, a.state]));
    const at = this.clock();
    for (const a of next.flows.find((f) => f.name === "board")?.agents ?? []) {
      const from = fresh.has(a.id) ? null : was.get(a.id) ?? null;
      if (from !== a.state) (this.lanes[a.id] ??= []).push({ at, from, to: a.state });
    }
    this.snapshot = this.verdicts(next);
    for (const fn of this.listeners) fn(this.snapshot);
  }

  private verdicts(snap: Snapshot): Snapshot {
    const flows = snap.flows.map((f) =>
      f.name !== "board" ? f : { ...f, agents: f.agents.map((a): RawAgent => ({ ...a, moves: Object.fromEntries(columns(f.machine, a.state).map((c) => [c, ALLOWED])) })) },
    );
    return { ...snap, flows };
  }
}

const demoRecord = (card: RawAgent): TaskRecord => ({
  title: card.title,
  profile: card.model,
  priority: "Medium",
  labels: card.labels ?? ["demo"],
  milestone: card.milestone ?? "",
  dependencies: card.dependencies ?? [],
  description: card.description ?? "A synthetic task used by the public StarPulse preview.",
  plan: "1. Inspect the task\n2. Make the smallest safe change\n3. Verify the result",
  notes: "This record contains no real board data.",
  acceptanceCriteria: [
    { n: 1, text: "The public preview can edit every field", checked: false },
    { n: 2, text: "The saved card refreshes immediately", checked: false },
  ],
  definitionOfDone: [{ n: 1, text: "The change is verified", checked: false }],
});

/** The snapshot a self-contained demo page embeds as `window.__FLOW_FIXTURE__`, null on a served page. */
export const embedded = (): DemoFixture | null => (globalThis as { __FLOW_FIXTURE__?: DemoFixture }).__FLOW_FIXTURE__ ?? null;

let server: DemoServer | null = null;
/** The page's one DemoServer when it embeds a fixture, else null: a served page asks starpulse.server. */
export const demoServer = (): DemoServer | null => {
  const fixture = embedded();
  const refuseEdits = new URLSearchParams(globalThis.location?.search ?? "").get("edit") === "refuse";
  return fixture ? (server ??= new DemoServer(fixture, undefined, refuseEdits)) : null;
};

/** `fetch` for the page's /api requests: answered by the demo server on a demo page, by starpulse.server otherwise. */
export const apiFetch = (url: string, init?: RequestInit): Promise<Response> => demoServer()?.fetch(url, init) ?? fetch(url, init);
