// The demo: `?demo` walks random legal transitions in random flows so every section moves, and a self-contained
// demo page (`starpulse.demo`) runs that walk inside a DemoServer that answers the page's /api requests itself.
import { demoLevel } from "./demoLevel";
import { columnsOf } from "./kanban";
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
        snap.settled[ag.id] = { state: e.target, at: Date.now() / 1000, created: ag.created ?? null, title: ag.title, model: ag.model };
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
  const idle = snap.dags.filter((d) => !d.active?.length); // a DAG with runs in flight moves by `stepRuns`
  if (idle.length && random() < 0.3) {
    const d = idle[Math.floor(random() * idle.length)];
    d.status = d.status === "running" ? (random() < 0.85 ? "succeeded" : "failed") : d.status === "queued" ? "running" : "queued";
    if (d.status === "queued") d.runId += "+";
  }
  return snap;
}

const iso = (at: number) => new Date(at * 1000).toISOString().replace(/\.\d+Z$/, "Z");

/**
 * One step of the fan-out the embedded demo plays: a run in flight enters its next step or ends, or a new run starts while
 * its pool has room, the pool's count following. A DAG with no pool or steps does not move.
 */
export function stepRuns(prev: Snapshot, random = Math.random): Snapshot {
  const fans = prev.dags.filter((d) => d.pool && d.steps.length && prev.pools?.some((p) => p.name === d.pool));
  if (!fans.length) return prev;
  const snap = structuredClone(prev), now = Date.now() / 1000;
  const action = random(), d = snap.dags.filter((x) => fans.some((f) => f.name === x.name))[Math.floor(random() * fans.length)];
  const pool = snap.pools!.find((p) => p.name === d.pool)!, active = (d.active ??= []), names = d.steps.map((s) => s.name);
  if (action < 0.5 && active.length) {
    const run = active[Math.floor(random() * active.length)], at = names.indexOf(run.step);
    if (at + 1 < names.length) {
      const step = names[at + 1];
      Object.assign(run, { step, stepStartedAt: iso(now), steps: { ...run.steps, [run.step]: "succeeded", [step]: "running" } });
    } else {
      active.splice(active.indexOf(run), 1);
      pool.running = Math.max(0, pool.running - 1);
      if (!active.length) Object.assign(d, { status: "succeeded", finishedAt: iso(now) });
    }
  } else if (action >= 0.5 && action < 0.75 && pool.running < pool.cap) {
    const runId = `${d.name.slice(d.name.indexOf("/") + 1)}-agent-demo-${100 + ++demoN}`;
    active.push({ runId, status: "running", startedAt: iso(now), step: names[0], stepStartedAt: iso(now), steps: Object.fromEntries(names.map((n, i) => [n, i ? "not_started" : "running"])) });
    pool.running++;
    Object.assign(d, { status: "running", runId, startedAt: iso(now), finishedAt: "" });
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
  "/api/archive": (server, _path, _query, init) => server.archive(String(init?.body ?? "{}")),
  "/api/tasks": (server, _path, _query, init) => server.create(String(init?.body ?? "{}")),
  "/api/forwarding": (server, _path, _query, init) => server.forwarding(init?.method ?? "GET", String(init?.body ?? "")),
  "/api/level": (server, _path, query) => {
    const { status, body } = demoLevel(server.snapshot.now, Number(query.get("hours") ?? 168), new URLSearchParams(globalThis.location?.search ?? ""));
    return json(body, status);
  },
};

/** The hub a demo page pretends to forward to: `refused` answers an opt-in 403 (a hub that keeps no names), `down` never answers, `none` is an instance with no `[forward]` block. */
export type ForwardDemo = "refused" | "down" | "none";
/** The fields `forward.FIELDS` lets leave the IC, by stream; `actor` and `assignee` name a person. */
const CONTRACT = {
  "machine:events": ["machine", "event", "task", "run", "actor", "assignee", "time"],
  "runs:events": ["time", "phase", "workflow", "run_id", "status", "step", "depends"],
};
const PERSON = ["actor", "assignee"];

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
  private created = new Set<string>();
  private optIn = false;
  private listeners = new Set<(s: Snapshot) => void>();
  private timer: ReturnType<typeof setTimeout> | undefined;

  constructor(fixture: DemoFixture, private clock: () => number = () => Date.now() / 1000, private refuseEdits = false, private forward?: ForwardDemo) {
    const { history, ...snap } = structuredClone(fixture);
    // the fixture's times are kept as ages, so what settled an hour before the capture settled an hour before the page opened
    const age = clock() - snap.now;
    for (const card of snap.flows.find((f) => f.name === "board")?.agents ?? []) if (card.created != null) card.created += age;
    for (const e of Object.values(snap.settled)) [e.at, e.created] = [e.at == null ? null : e.at + age, e.created == null ? null : e.created + age];
    this.lanes = history ?? {};
    this.records = Object.fromEntries((snap.flows.find((f) => f.name === "board")?.agents ?? []).map((card) => [card.id, demoRecord(card)]));
    this.snapshot = this.verdicts({ ...snap, capabilities: { edit: true, archive: true, create: true } });
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

  /** One step of the walk, its Board lane changes recorded; a card it settles stays settled and new work created now takes its place, so the Board never drains.
   * A card the viewer created stays out of the walk, so it stays where it landed until the viewer moves it. */
  step(random = Math.random) {
    const walked = structuredClone(this.snapshot);
    const held = walked.flows.find((f) => f.name === "board");
    const created = held?.agents.filter((a) => this.created.has(a.id)) ?? [];
    if (held) held.agents = held.agents.filter((a) => !this.created.has(a.id));
    const next = stepRuns(demoStep(walked, random), random);
    const board = next.flows.find((f) => f.name === "board");
    const prev = held?.agents ?? [];
    const fresh = new Set<string>();
    if (board) {
      board.agents.push(...created);
      const lane = board.machine.mainLine?.[1] ?? board.machine.states.find((s) => s.initial)?.id ?? board.machine.states[0].id;
      const ids = [...board.agents, ...prev].map((a) => a.id).concat(Object.keys(next.settled));
      let n = Math.max(0, ...ids.map((id) => Number(id.match(/\d+$/)?.[0] ?? 0)));
      for (const card of prev.filter((a) => a.id in next.settled && !(a.id in this.snapshot.settled))) {
        next.settled[card.id].at = this.clock();
        const work = { ...card, id: `DEMO-${++n}`, state: lane, moves: undefined, created: this.clock() };
        this.records[work.id] = demoRecord(work);
        fresh.add(work.id);
        board.agents.push(work);
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

  /** Archive `task` as the served writer would: the card and its record leave the board, unless a review fixture makes the writer refuse. */
  archive(raw: string): Response {
    let task: unknown;
    try { task = (JSON.parse(raw) as { task?: unknown }).task; } catch { task = undefined; }
    if (typeof task !== "string") return json({ error: "invalid archive" }, 400);
    if (!this.snapshot.flows.find((f) => f.name === "board")?.agents.some((a) => a.id === task)) return json({ error: `${task} is not on the board` }, 404);
    if (this.refuseEdits) return json({ error: "The demo writer refused this archive; the task was not archived.", skill: "completing-tasks" }, 409);
    const next = structuredClone(this.snapshot);
    const board = next.flows.find((f) => f.name === "board")!;
    board.agents = board.agents.filter((a) => a.id !== task);
    delete this.records[task];
    this.publish(next);
    return json({ task });
  }

  /** Create a task in the Board's starting lane as the served writer would, unless a review fixture makes the writer refuse. */
  create(raw: string): Response {
    let sent: Record<string, unknown>;
    try { sent = JSON.parse(raw) as Record<string, unknown>; } catch { sent = {}; }
    const { title } = sent;
    if (typeof title !== "string" || !title.trim()) return json({ error: 'a create needs {"title": "<1 to 300 characters>"}' }, 400);
    const text = (field: string) => (typeof sent[field] === "string" ? (sent[field] as string).trim() : "");
    const list = (field: string) => (Array.isArray(sent[field]) ? (sent[field] as unknown[]).filter((v): v is string => typeof v === "string") : []);
    if (this.refuseEdits) return json({ error: "The demo writer refused this create; the task was not created.", skill: "completing-tasks" }, 409);
    const next = structuredClone(this.snapshot);
    const board = next.flows.find((f) => f.name === "board");
    if (!board) return json({ error: "this board does not create tasks" }, 404);
    const prefix = board.agents[0]?.id.match(/^(.*?)\d+$/)?.[1] ?? "TASK-";
    const ids = board.agents.map((a) => a.id).concat(Object.keys(next.settled));
    const id = `${prefix}${Math.max(0, ...ids.map((n) => Number(n.match(/\d+$/)?.[0] ?? 0))) + 1}`;
    const lane = startingLane(board.machine);
    const card: RawAgent = {
      id, title: title.trim(), state: lane, model: text("assignee"), labels: list("labels"), milestone: text("milestone"),
      dependencies: list("dependencies"), description: text("description"),
    };
    board.agents.push(card);
    this.created.add(id);
    this.records[id] = {
      ...demoRecord(card), priority: text("priority"), plan: "", notes: "", definitionOfDone: [],
      acceptanceCriteria: list("acceptanceCriteria").map((item, i) => ({ n: i + 1, text: item, checked: false })),
    };
    this.publish(next, new Set([id]));
    return json({ task: id }, 201);
  }

  /** `/api/forwarding` as starpulse.server answers it: the moves the forwarder would send next, cut as it cuts them, and a PUT that flips the opt-in. */
  forwarding(method: string, raw: string): Response {
    if (this.forward === "none") return method === "PUT" ? json({ error: "this instance forwards nothing" }, 404) : json({ configured: false });
    if (method === "PUT") {
      let sent: unknown;
      try { sent = (JSON.parse(raw) as { opt_in?: unknown }).opt_in; } catch { sent = undefined; }
      if (typeof sent !== "boolean") return json({ error: 'forwarding takes {"opt_in": true} or {"opt_in": false}' }, 400);
      this.optIn = sent;
    } else if (method !== "GET") return json({ error: `${method} is not served here` }, 405);
    const names = this.optIn && this.forward !== "refused";
    const at = this.clock();
    const board = this.snapshot.flows.find((f) => f.name === "board");
    return json({
      configured: true,
      url: "hub.demo/api/forward",
      optIn: this.optIn,
      names,
      refused: this.optIn && this.forward === "refused",
      lastSent: this.forward === "down" ? null : at - 12,
      problem: this.forward === "down" ? "hub unreachable: connection refused" : this.optIn && this.forward === "refused" ? "hub answered 403: this hub keeps aggregates only" : null,
      next: (board?.agents ?? []).slice(0, 10).map((a, i) => ({
        stream: "machine:events",
        fields: { machine: "board", event: "MOVED", task: a.id, ...(names ? { actor: "demo-agent" } : {}), time: at - 5 * (i + 1) },
        kept: ["from", "to"],
      })),
      more: false,
      contract: Object.fromEntries(Object.entries(CONTRACT).map(([stream, fields]) => [stream, fields.map((field) => ({ field, person: PERSON.includes(field) }))])),
    });
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

/** Where a new task starts: the machine's initial state when the Kanban draws it as a column, else the first column. */
const startingLane = (machine: Machine): string => {
  const lanes = columnsOf(Object.fromEntries(machine.states.map((s) => [s.id, s.name])));
  const initial = machine.states.find((s) => s.initial)?.id ?? "";
  return lanes.includes(initial) ? initial : lanes[0];
};

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
  const query = new URLSearchParams(globalThis.location?.search ?? "");
  const refuseEdits = query.get("edit") === "refuse";
  const forward = (["refused", "down", "none"] as const).find((state) => state === query.get("forward"));
  return fixture ? (server ??= new DemoServer(fixture, undefined, refuseEdits, forward)) : null;
};

/** A write says it is JSON, body or none: starpulse.server refuses any other, which a web page on another site cannot send without asking first. */
const asJson = (init?: RequestInit): RequestInit | undefined => {
  if (!init?.method || init.method === "GET") return init;
  const headers = new Headers(init.headers);
  if (!headers.has("content-type")) headers.set("content-type", "application/json");
  return { ...init, headers };
};

/** `fetch` for the page's /api requests: answered by the demo server on a demo page, by starpulse.server otherwise. */
export const apiFetch = (url: string, init?: RequestInit): Promise<Response> => demoServer()?.fetch(url, init) ?? fetch(url, asJson(init));
