// The Autopilot card's quiet hours: the daily window in which autopilot starts no task, kept by the server with the switch
// (`PUT /api/autopilot {"quietHours": ...}`). The server validates it; this store only asks, and shows what the server answered.
import { apiFetch } from "../../api/apiFetch";
import { ROUTE } from "../autopilot/autopilot";

/** The window as the server keeps it: `start` up to `end`, `HH:MM` on `timezone`'s clock; an end before the start runs past midnight. */
export interface Window {
  start: string;
  end: string;
  timezone: string;
}
/** The controls: whether the window is on, and its times. */
export interface Draft {
  on: boolean;
  start: string;
  end: string;
}
/** What the controls offer when the server keeps no window. */
const OFFER: Draft = { on: false, start: "22:00", end: "07:00" };

export type Phase = { kind: "idle" } | { kind: "saving" } | { kind: "saved"; at: number } | { kind: "refused"; reason: string };
export interface QuietView {
  /** Whether the server has answered once; until then there is no window to show. */
  loaded: boolean;
  /** The window the server last answered, null for none. */
  current: Window | null;
  draft: Draft;
  phase: Phase;
  /** Why the window could not be read, empty when it could. */
  unavailable: string;
}

type Answer = { ok: true; window: Window | null } | { ok: false; reason: string };

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

async function ask(fetcher: typeof apiFetch, init: RequestInit | undefined, unreachable: string): Promise<Answer> {
  let response: Response;
  try {
    response = await fetcher(ROUTE, init);
  } catch {
    return { ok: false, reason: unreachable };
  }
  const body: unknown = await response.json().catch(() => null);
  if (response.ok && isRecord(body)) return { ok: true, window: isRecord(body.quietHours) ? (body.quietHours as unknown as Window) : null };
  const error = isRecord(body) && typeof body.error === "string" ? body.error : "";
  return { ok: false, reason: error || `the server answered ${response.status}` };
}

const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const drafted = (window: Window | null): Draft => (window ? { on: true, start: window.start, end: window.end } : OFFER);

export class QuietHoursStore {
  private view: QuietView = { loaded: false, current: null, draft: OFFER, phase: { kind: "idle" }, unavailable: "" };
  private listeners = new Set<() => void>();
  constructor(
    private fetcher: typeof apiFetch = apiFetch,
    private localZone: () => string = browserZone,
    private clock: () => number = () => Date.now() / 1000,
  ) {}

  get = () => this.view;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<QuietView>) {
    this.view = { ...this.view, ...patch };
    for (const fn of this.listeners) fn();
  }

  async load(): Promise<void> {
    const answer = await ask(this.fetcher, undefined, "the server did not answer");
    if (answer.ok) this.set({ loaded: true, current: answer.window, draft: drafted(answer.window), unavailable: "" });
    else this.set({ unavailable: answer.reason });
  }

  /** The zone the times are read in: the kept window's own, else this browser's, which a save sends. */
  zone = () => this.view.current?.timezone ?? this.localZone();

  /** Change the controls; the last message no longer describes them. */
  edit(patch: Partial<Draft>) {
    this.set({ draft: { ...this.view.draft, ...patch }, phase: { kind: "idle" } });
  }

  /** Whether the controls differ from the kept window, which is when Save is offered. */
  dirty = () => {
    const { draft, current } = this.view;
    return current ? !draft.on || draft.start !== current.start || draft.end !== current.end : draft.on;
  };

  /** Keep the controls as the window, read in this browser's zone, or clear it when they are off. */
  async save(): Promise<void> {
    if (this.view.phase.kind === "saving") return;
    const { on, start, end } = this.view.draft;
    const quietHours = on ? { start, end, timezone: this.localZone() } : null;
    this.set({ phase: { kind: "saving" } });
    const answer = await ask(this.fetcher, { method: "PUT", body: JSON.stringify({ quietHours }) }, "the change did not reach the server");
    if (answer.ok) this.set({ current: answer.window, draft: drafted(answer.window), phase: { kind: "saved", at: this.clock() } });
    else this.set({ phase: { kind: "refused", reason: answer.reason } });
  }
}
