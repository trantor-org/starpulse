// The server's health: one `health` subscription on POST /graphql, sent when it opens and again on each change of the components, the build or the restart.

import { apiFetch } from "./apiFetch";
import { frames, hush } from "./sse";

const SUBSCRIPTION = "subscription { health { components { name ready detail } build restarting at } }";

export interface Health {
  /** Each readiness component of `GET /api/health`: `store`, `board`, `writer`, `contexts`. */
  components: { name: string; ready: boolean; detail: string }[];
  /** The page build the server serves, or null when it names none. */
  build: string | null;
  /** The server announced it is restarting. */
  restarting: boolean;
  /** The server's clock, in epoch seconds, when it made this event. */
  at: number;
}

export interface HealthHandlers {
  health(h: Health): void;
  /** The subscription ended, unless `close` stopped it: the server closed it, refused it or could not be reached. */
  end(): void;
}

/** What opens a health subscription; `openStream` takes it as a seam. */
export type Watch = (on: HealthHandlers) => { close(): void };

type Post = (url: string, init?: RequestInit) => Promise<Response>;

export function openHealth(on: HealthHandlers, post: Post = apiFetch): { close(): void } {
  const stop = new AbortController(), quiet = hush(stop.signal);
  const run = async () => {
    const resp = await post("/graphql", { method: "POST", body: JSON.stringify({ query: SUBSCRIPTION }), signal: quiet.signal });
    if (!resp.ok || !resp.body) return;
    for await (const frame of frames(resp.body, quiet.heard)) {
      const health = (frame as { data?: { health?: Health } }).data?.health;
      if (health && !stop.signal.aborted) on.health(health);
    }
  };
  run().finally(quiet.done).then(
    () => stop.signal.aborted || on.end(),
    () => stop.signal.aborted || on.end(),
  );
  return { close: () => stop.abort() };
}
