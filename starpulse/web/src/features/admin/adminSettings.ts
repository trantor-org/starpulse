// What Admin keeps on the server for every device: `GET /api/admin` carries the display and theme choices beside the scheduler's status,
// and a `PUT` names only the group it changes. The two stores read it once at boot and write each change as it is made.
import { apiFetch } from "../../api/apiFetch";

export const ROUTE = "/api/admin";

/** The `display` and `theme` an Admin answer holds, as the server sent them; each store sanitizes its own. */
export interface Settings {
  display?: unknown;
  theme?: unknown;
}

/** The server's settings, or null when it does not answer: the stores then keep what they draw. */
export async function readSettings(fetcher: typeof apiFetch = apiFetch): Promise<Settings | null> {
  try {
    const response = await fetcher(ROUTE);
    return response.ok ? ((await response.json()) as Settings) : null;
  } catch {
    return null;
  }
}

/** How the last write ended: nothing yet, kept for every device, or not kept with the reason the server gave. */
export type Saved = { kind: "idle" } | { kind: "saved" } | { kind: "refused"; reason: string };

/** Keeps `patch` on the server; a refusal or silence says why, so the caller shows what the server holds. */
export async function writeSettings(fetcher: typeof apiFetch, patch: Settings): Promise<Saved> {
  try {
    const response = await fetcher(ROUTE, { method: "PUT", body: JSON.stringify(patch) });
    if (response.ok) return { kind: "saved" };
    const body: { error?: string } | null = await response.json().catch(() => null);
    return { kind: "refused", reason: body?.error ?? `the server answered ${response.status}` };
  } catch {
    return { kind: "refused", reason: "the server did not answer" };
  }
}
