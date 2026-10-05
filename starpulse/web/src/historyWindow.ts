// The Admin view's Server card: the one setting the server keeps for every viewer, how far back a task's latest move counts. The server
// validates it (1-72 hours) and persists the override; this store only asks, and shows what the server answered.
import { apiFetch } from "./demo";

const ROUTE = "/api/history-window";
/** The window the server draws with, the default the unit declares, and whether an Admin override is what is in effect. */
export interface WindowState {
  hours: number;
  default: number;
  overridden: boolean;
}
/** Quick picks beside the input. */
export const CHIPS = [1, 6, 24, 72] as const;

export type Phase = { kind: "idle" } | { kind: "saving" } | { kind: "saved"; at: number } | { kind: "refused"; reason: string };
export interface WindowView {
  /** What the server last answered; null until it has, or when it cannot be read. */
  current: WindowState | null;
  /** The input's text. */
  draft: string;
  phase: Phase;
  /** Why the window could not be read, empty when it could. */
  unavailable: string;
}

type Answer = { ok: true; state: WindowState } | { ok: false; reason: string };

async function ask(fetcher: typeof apiFetch, init: RequestInit | undefined, unreachable: string): Promise<Answer> {
  let response: Response;
  try {
    response = await fetcher(ROUTE, init);
  } catch {
    return { ok: false, reason: unreachable };
  }
  const body: (Partial<WindowState> & { error?: string }) | null = await response.json().catch(() => null);
  if (response.ok && body) return { ok: true, state: body as WindowState };
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}` };
}

export class HistoryWindowStore {
  private view: WindowView = { current: null, draft: "", phase: { kind: "idle" }, unavailable: "" };
  private listeners = new Set<() => void>();
  constructor(private fetcher: typeof apiFetch = apiFetch, private clock: () => number = () => Date.now() / 1000) {}

  get = () => this.view;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<WindowView>) {
    this.view = { ...this.view, ...patch };
    for (const fn of this.listeners) fn();
  }

  async load(): Promise<void> {
    const answer = await ask(this.fetcher, undefined, "the server did not answer");
    if (answer.ok) this.set({ current: answer.state, draft: String(answer.state.hours), unavailable: "" });
    else this.set({ unavailable: answer.reason });
  }

  /** The input's new text; the last message no longer describes it. */
  edit(text: string) {
    this.set({ draft: text, phase: { kind: "idle" } });
  }

  /** Whether the input differs from the window, which is when Save is offered. */
  dirty = () => this.view.current !== null && this.view.draft.trim() !== String(this.view.current.hours);

  /** Ask the server to keep the input as the window. A number is sent as one and anything else as typed, so the server's refusal names it. */
  save(): Promise<void> {
    const text = this.view.draft.trim();
    const hours = text !== "" && Number.isFinite(Number(text)) ? Number(text) : this.view.draft;
    return this.send({ method: "PUT", body: JSON.stringify({ hours }) });
  }

  /** Delete the override: the window returns to the declared default. */
  reset(): Promise<void> {
    return this.send({ method: "DELETE" });
  }

  private async send(init: RequestInit): Promise<void> {
    if (this.view.phase.kind === "saving") return;
    this.set({ phase: { kind: "saving" } });
    const answer = await ask(this.fetcher, init, "the change did not reach the server");
    if (answer.ok) this.set({ current: answer.state, draft: String(answer.state.hours), phase: { kind: "saved", at: this.clock() } });
    else this.set({ phase: { kind: "refused", reason: answer.reason } });
  }
}
