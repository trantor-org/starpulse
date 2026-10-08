// The contract report behind the Ledger's doctor banner: one /api/doctor read, held and re-read once a minute while the page asks for it.
import { apiFetch } from "../../api/apiFetch";
import type { ContractReport } from "../../api";

export interface Contract {
  /** The last report the server gave, null until one has; asking starts a read when none is held or the one held is stale. */
  report(): ContractReport | null;
}

export interface ContractOptions {
  /** Called once a read lands, so the Ledger redraws its banner. */
  onChange: () => void;
  fetch?: (url: string) => Promise<{ ok: boolean; json(): Promise<unknown> }>;
  now?: () => number;
  /** How long a report is fresh, in seconds. */
  ttl?: number;
}

export function createContract({ onChange, fetch: get = (u) => apiFetch(u), now = () => Date.now() / 1000, ttl = 60 }: ContractOptions): Contract {
  let held: ContractReport | null = null, at = -Infinity, busy = false;
  return {
    report() {
      if (!busy && now() - at >= ttl) {
        busy = true;
        get("/api/doctor")
          .then((r) => (r.ok ? (r.json() as Promise<ContractReport>) : held))
          .catch(() => held)
          .then((report) => {
            held = report;
            at = now();
            busy = false;
            onChange();
          });
      }
      return held;
    },
  };
}
