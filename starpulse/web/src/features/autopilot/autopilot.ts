// The Admin view's Autopilot card: the global switch, the harness it starts on, and what the admission loop sees, read from /api/autopilot.
// Off stops admission only: sessions already running keep running, and the card says how many.
import { apiFetch } from "../../api/apiFetch";
import type { AutopilotDimension, AutopilotStatus } from "../../api";

export const ROUTE = "/api/autopilot";
export const HARNESSES_ROUTE = "/api/harnesses";

/** One capacity dimension as the card draws it: what is in use against the limit admission holds it under. `detail` is the meter's tooltip. */
export interface Dimension {
  name: string;
  label: string;
  used: number;
  limit: number;
  unit: string;
  detail: string;
}
/** A session autopilot started and that is still running its task. */
export interface InFlight {
  task: string;
  title: string;
  model: string;
  started: number;
  url: string;
}
/** The task the loop would admit next, and whether it fits now or which dimension it waits on. */
export interface NextPick {
  task: string;
  title: string;
  verdict: "starting" | "waits";
  reason: string;
}
/** A harness `GET /api/harnesses` names for the Admission Segments picker. */
export interface HarnessOption {
  name: string;
  label: string;
  /** False when the harness cannot open a session; `reason` is the disabled tooltip. */
  sessions: boolean;
  reason: string;
}
/** A harness whose admission is paused until `until` after a usage or credit limit. */
export interface Pause {
  harness: string;
  until: number;
  reason: string;
}
/** One harness's in-flight count against its own session cap. */
export interface HarnessSessions {
  use: number;
  limit: number;
}
export interface AutopilotState {
  on: boolean;
  /** The harness the loop starts sessions on; defaults to claude. */
  harness: string;
  sampledAt: number | null;
  dimensions: Dimension[];
  /** The sessions autopilot started, null while the server does not list them (the Sessions meter's count still reads). */
  inFlight: InFlight[] | null;
  /** The pick the loop would admit next, null when the server names none. */
  next: NextPick | null;
  /** Harnesses whose admission is paused until `until`; empty when none are. */
  pauses: Pause[];
  /** Each harness's in-flight count against its session cap; empty when the server serves none. */
  sessionsByHarness: Record<string, HarnessSessions>;
}

export type Phase = { kind: "idle" } | { kind: "saving" } | { kind: "refused"; reason: string };
export interface AutopilotView {
  /** What the server last answered; null until it has, or while it cannot be read. */
  current: AutopilotState | null;
  phase: Phase;
  /** Why the status could not be read, empty when it could. */
  unavailable: string;
  /** The harnesses the Admission Segments offer; empty until `GET /api/harnesses` answers. */
  harnesses: HarnessOption[];
}

/** A dimension's meter state: quiet under 80% of its limit, near from there to the limit, over past it. */
export const level = (d: Dimension): "ok" | "near" | "over" => (d.used > d.limit ? "over" : d.used >= 0.8 * d.limit ? "near" : "ok");

const LABELS: Record<AutopilotDimension["name"], { label: string; unit: string; detail: (used: number, limit: number) => string }> = {
  cpu: { label: "CPU", unit: "%", detail: (_used, limit) => `Host CPU in use. Admission holds it under ${limit}%.` },
  memory: { label: "RAM", unit: "%", detail: (_used, limit) => `Host memory in use. Admission holds it under ${limit}%.` },
  sessions: { label: "Sessions", unit: "", detail: () => "Autopilot sessions running. Click for the list." },
  review: { label: "Review", unit: " pts", detail: (used, limit) => `Points waiting in Review: ${used}. Admission stops at ${limit} so review keeps up.` },
};

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown, fallback: string) => (typeof v === "string" ? v : fallback);

function dimension(raw: unknown): Dimension | null {
  if (!isRecord(raw) || typeof raw.name !== "string" || typeof raw.use !== "number" || typeof raw.limit !== "number") return null;
  const known = (LABELS as Record<string, (typeof LABELS)[AutopilotDimension["name"]] | undefined>)[raw.name];
  return {
    name: raw.name,
    label: known?.label ?? raw.name,
    used: raw.use,
    limit: raw.limit,
    unit: known?.unit ?? "",
    detail: known?.detail(raw.use, raw.limit) ?? "",
  };
}

function session(raw: unknown): InFlight | null {
  if (!isRecord(raw) || typeof raw.task !== "string") return null;
  return {
    task: raw.task,
    title: str(raw.title, raw.task),
    model: str(raw.model, ""),
    started: typeof raw.started === "number" ? raw.started : 0,
    url: str(raw.url, ""),
  };
}

function pick(raw: unknown): NextPick | null {
  if (!isRecord(raw) || typeof raw.task !== "string") return null;
  return {
    task: raw.task,
    title: str(raw.title, raw.task),
    verdict: raw.verdict === "starting" ? "starting" : "waits",
    reason: str(raw.reason, ""),
  };
}

function pause(raw: unknown): Pause | null {
  if (!isRecord(raw) || typeof raw.harness !== "string" || typeof raw.until !== "number") return null;
  return { harness: raw.harness, until: raw.until, reason: str(raw.reason, "usage limit") };
}

function sessionsByHarness(raw: unknown): Record<string, HarnessSessions> | null {
  if (raw === undefined) return {};
  if (!isRecord(raw)) return null;
  const out: Record<string, HarnessSessions> = {};
  for (const [name, row] of Object.entries(raw)) {
    if (!isRecord(row) || typeof row.use !== "number" || typeof row.limit !== "number") return null;
    out[name] = { use: row.use, limit: row.limit };
  }
  return out;
}

function harnessOptions(body: unknown): HarnessOption[] {
  if (!isRecord(body) || !Array.isArray(body.harnesses)) return [];
  return body.harnesses.flatMap((raw) => {
    if (!isRecord(raw) || typeof raw.name !== "string") return [];
    return [{
      name: raw.name,
      label: str(raw.label, raw.name),
      sessions: raw.sessions !== false,
      reason: str(raw.reason, ""),
    }];
  });
}

/** The card's state from an answer, or null when the answer is not an autopilot status. `inFlight`, `next`, `pauses` and `sessionsByHarness` are additive: absent is fine, present must hold. */
function parse(body: unknown): AutopilotState | null {
  const status = body as Partial<AutopilotStatus> & { inFlight?: unknown; next?: unknown; pauses?: unknown; sessionsByHarness?: unknown };
  if (!isRecord(body) || typeof status.enabled !== "boolean" || !Array.isArray(status.dimensions)) return null;
  const dimensions = status.dimensions.map(dimension);
  if (dimensions.some((d) => d === null)) return null;
  let inFlight: InFlight[] | null = null;
  if (status.inFlight !== undefined) {
    if (!Array.isArray(status.inFlight)) return null;
    const sessions = status.inFlight.map(session);
    if (sessions.some((s) => s === null)) return null;
    inFlight = sessions as InFlight[];
  }
  let next: NextPick | null = null;
  if (status.next !== undefined && status.next !== null) {
    next = pick(status.next);
    if (!next) return null;
  }
  let pauses: Pause[] = [];
  if (status.pauses !== undefined) {
    if (!Array.isArray(status.pauses)) return null;
    const rows = status.pauses.map(pause);
    if (rows.some((p) => p === null)) return null;
    pauses = rows as Pause[];
  }
  const byHarness = sessionsByHarness(status.sessionsByHarness);
  if (byHarness === null) return null;
  const harness = typeof status.harness === "string" && status.harness ? status.harness : "claude";
  return {
    on: status.enabled,
    harness,
    sampledAt: status.sampledAt ?? null,
    dimensions: dimensions as Dimension[],
    inFlight,
    next,
    pauses,
    sessionsByHarness: byHarness,
  };
}

type Answer = { ok: true; state: AutopilotState } | { ok: false; reason: string };

async function ask(fetcher: typeof apiFetch, init: RequestInit | undefined, unreachable: string): Promise<Answer> {
  let response: Response;
  try {
    response = await fetcher(ROUTE, init);
  } catch {
    return { ok: false, reason: unreachable };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.ok) {
    const state = parse(body);
    return state ? { ok: true, state } : { ok: false, reason: "the server's answer is not an autopilot status" };
  }
  const error = isRecord(body) && typeof body.error === "string" ? body.error : "";
  return { ok: false, reason: error || `the server answered ${response.status}` };
}

/** Stores that take `/api/events` `autopilot` bodies; the renderer pushes each one. */
const streamListeners = new Set<(body: unknown) => void>();

/** Hand an `autopilot` stream event to every open card store. */
export function pushAutopilotStatus(body: unknown): void {
  for (const fn of streamListeners) fn(body);
}

export class AutopilotStore {
  private view: AutopilotView = { current: null, phase: { kind: "idle" }, unavailable: "", harnesses: [] };
  private listeners = new Set<() => void>();
  constructor(private fetcher: typeof apiFetch = apiFetch) {
    streamListeners.add(this.accept);
  }

  /** Drop the stream listener when the card unmounts with this store. */
  dispose(): void {
    streamListeners.delete(this.accept);
  }

  get = () => this.view;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<AutopilotView>) {
    this.view = { ...this.view, ...patch };
    for (const fn of this.listeners) fn();
  }

  /** Apply a status body from the stream; a shape the store refuses leaves the last reading. */
  accept = (body: unknown): void => {
    const state = parse(body);
    if (state) this.set({ current: state, unavailable: "" });
  };

  /** Read the status and harnesses once (connect sync); a status that cannot be read leaves the last reading on the card. */
  async load(): Promise<void> {
    const [answer, harnesses] = await Promise.all([
      ask(this.fetcher, undefined, "the server did not answer"),
      this.fetcher(HARNESSES_ROUTE).then((r) => r.json()).then(harnessOptions).catch(() => [] as HarnessOption[]),
    ]);
    if (answer.ok) this.set({ current: answer.state, unavailable: "", harnesses });
    else this.set({ unavailable: answer.reason, harnesses });
  }

  /** Ask the server to admit tasks or stop admitting; a refusal leaves the switch as it was and names why. */
  async setOn(on: boolean): Promise<void> {
    if (this.view.phase.kind === "saving") return;
    this.set({ phase: { kind: "saving" } });
    const answer = await ask(this.fetcher, { method: "PUT", body: JSON.stringify({ enabled: on }) }, "the change did not reach the server");
    if (answer.ok) this.set({ current: answer.state, unavailable: "", phase: { kind: "idle" } });
    else this.set({ phase: { kind: "refused", reason: answer.reason } });
  }

  /** Ask the server to start sessions on another harness; a refusal leaves the pick as it was and names why. */
  async setHarness(harness: string): Promise<void> {
    if (this.view.phase.kind === "saving") return;
    this.set({ phase: { kind: "saving" } });
    const answer = await ask(this.fetcher, { method: "PUT", body: JSON.stringify({ harness }) }, "the change did not reach the server");
    if (answer.ok) this.set({ current: answer.state, unavailable: "", phase: { kind: "idle" } });
    else this.set({ phase: { kind: "refused", reason: answer.reason } });
  }

  dismiss() {
    this.set({ phase: { kind: "idle" } });
  }
}
