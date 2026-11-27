// One GraphQL subscription over `POST /graphql` (graphql-sse "distinct connections"): the `next` frames of its SSE body, one per change.

import { apiFetch } from "./apiFetch";
import { frames, hush } from "./sse";

export type Post = (url: string, init?: RequestInit) => Promise<Response>;

/** Why a subscription ended: the server closed it, or the position it held is gone and the read must be taken again. */
export type Ended = "closed" | "reread";

/** Subscribe to `field(from: $from)` with `query`; each change after `from` goes to `change`, and `end` says why the stream stopped, unless `close` stopped it. */
export function follow<T>(
  query: string,
  field: string,
  from: number,
  on: { change(data: T): void; end(why: Ended): void },
  post: Post = apiFetch,
): { close(): void } {
  const stop = new AbortController(), quiet = hush(stop.signal);
  const run = async (): Promise<Ended> => {
    const resp = await post("/graphql", { method: "POST", body: JSON.stringify({ query, variables: { from } }), signal: quiet.signal });
    if (resp.status === 410) return "reread";
    if (!resp.ok || !resp.body) return "closed";
    for await (const frame of frames(resp.body, quiet.heard)) {
      const change = (frame as { data?: Record<string, T | undefined> }).data?.[field];
      if (change && !stop.signal.aborted) on.change(change);
    }
    return "closed";
  };
  run().finally(quiet.done).then(
    (why) => stop.signal.aborted || on.end(why),
    () => stop.signal.aborted || on.end("closed"),
  );
  return { close: () => stop.abort() };
}
