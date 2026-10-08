// The Admin view's Forwarding card: what this instance's forwarder would send the hub next, and the opt-in that lets a person's name go with it.
// The server cuts the listing with the same function that cuts the batch; this store only asks, and shows what the server answered.
import { apiFetch } from "../../api/apiFetch";

export const ROUTE = "/api/forwarding";

/** One entry of a stream as the batch would carry it, and the names of the fields that stay on this instance. */
export interface ForwardRow {
  stream: string;
  fields: Record<string, string | number | string[]>;
  kept: string[];
}
/** A field a stream's contract lets leave, and whether it names a person (which leaves only after opt-in). */
export interface ContractField {
  field: string;
  person: boolean;
}
export interface ForwardStatus {
  configured: true;
  /** The hub's ingest address. */
  url: string;
  /** The instance's own flag, and whether a person's name leaves in the next batch (an opt-in the hub refused does not). */
  optIn: boolean;
  names: boolean;
  refused: boolean;
  /** When the hub last acknowledged a batch since this process started, epoch seconds. */
  lastSent: number | null;
  /** Why the last batch did not go through, null once one does. */
  problem: string | null;
  next: ForwardRow[];
  more: boolean;
  contract: Record<string, ContractField[]>;
}
export type ForwardingState = ForwardStatus | { configured: false };

export type Phase = { kind: "idle" } | { kind: "saving" } | { kind: "saved"; at: number } | { kind: "refused"; reason: string };
export interface ForwardingView {
  /** What the server last answered; null until it has, or when it cannot be read. */
  current: ForwardingState | null;
  phase: Phase;
  /** Why the status could not be read, empty when it could. */
  unavailable: string;
}

type Answer = { ok: true; state: ForwardingState } | { ok: false; reason: string };

async function ask(fetcher: typeof apiFetch, init: RequestInit | undefined, unreachable: string): Promise<Answer> {
  let response: Response;
  try {
    response = await fetcher(ROUTE, init);
  } catch {
    return { ok: false, reason: unreachable };
  }
  const body: (Partial<ForwardStatus> & { error?: string }) | null = await response.json().catch(() => null);
  if (response.ok && body) return { ok: true, state: body as ForwardingState };
  return { ok: false, reason: body?.error ?? `the server answered ${response.status}` };
}

export class ForwardingStore {
  private view: ForwardingView = { current: null, phase: { kind: "idle" }, unavailable: "" };
  private listeners = new Set<() => void>();
  constructor(private fetcher: typeof apiFetch = apiFetch, private clock: () => number = () => Date.now() / 1000) {}

  get = () => this.view;
  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };
  private set(patch: Partial<ForwardingView>) {
    this.view = { ...this.view, ...patch };
    for (const fn of this.listeners) fn();
  }

  /** Read the status; one that cannot be read leaves the last status on the card. */
  async load(): Promise<void> {
    const answer = await ask(this.fetcher, undefined, "the server did not answer");
    if (answer.ok) this.set({ current: answer.state, unavailable: "" });
    else this.set({ unavailable: answer.reason });
  }

  /** Ask the server to let a person's name leave with the batches, or stop it; it applies at the next send. */
  async setOptIn(optIn: boolean): Promise<void> {
    if (this.view.phase.kind === "saving") return;
    this.set({ phase: { kind: "saving" } });
    const answer = await ask(this.fetcher, { method: "PUT", body: JSON.stringify({ opt_in: optIn }) }, "the change did not reach the server");
    if (answer.ok) this.set({ current: answer.state, unavailable: "", phase: { kind: "saved", at: this.clock() } });
    else this.set({ phase: { kind: "refused", reason: answer.reason } });
  }
}
