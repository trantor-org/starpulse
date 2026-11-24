// The jobs the Jobs page lists: one POST /api/jobs read, then the jobChanges subscription on POST /graphql from the position it returned.

import { apiFetch } from "./apiFetch";
import type { Dag, Jobs } from ".";

type Post = (url: string, init?: RequestInit) => Promise<Response>;

const SUBSCRIPTION = "subscription ($from: Int!) { jobChanges(from: $from) { jobs error } }";

/** Why a subscription ended: the server closed it, or the position it held is gone and the list must be read again. */
export type Ended = "closed" | "reread";

export async function readJobs(post: Post = apiFetch): Promise<Jobs | null> {
  const resp = await post("/api/jobs", { method: "POST", body: "{}" });
  return resp.ok ? ((await resp.json()) as Jobs) : null;
}

/** The `next` frames of one SSE body, each as its parsed data, until the stream ends. */
async function* frames(body: ReadableStream<Uint8Array>): AsyncGenerator<unknown> {
  const reader = body.getReader(), text = new TextDecoder();
  let rest = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    rest += text.decode(value, { stream: true });
    for (let at = rest.indexOf("\n\n"); at >= 0; at = rest.indexOf("\n\n")) {
      const lines = rest.slice(0, at).split("\n");
      rest = rest.slice(at + 2);
      if (lines.some((l) => l === "event: next")) yield JSON.parse(lines.filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n"));
    }
  }
}

/** Each change after `from` hands over the full job list and the runs error; `end` says why the stream stopped, unless `close` stopped it. */
export function followJobs(
  from: number,
  on: { jobs(list: Dag[], error: string | null): void; end(why: Ended): void },
  post: Post = apiFetch,
): { close(): void } {
  const stop = new AbortController();
  const run = async () => {
    const resp = await post("/graphql", { method: "POST", body: JSON.stringify({ query: SUBSCRIPTION, variables: { from } }), signal: stop.signal });
    if (resp.status === 410) return "reread";
    if (!resp.ok || !resp.body) return "closed";
    for await (const frame of frames(resp.body)) {
      const change = (frame as { data?: { jobChanges?: { jobs: Dag[]; error: string | null } } }).data?.jobChanges;
      if (change && !stop.signal.aborted) on.jobs(change.jobs, change.error);
    }
    return "closed";
  };
  run().then(
    (why) => stop.signal.aborted || on.end(why),
    () => stop.signal.aborted || on.end("closed"),
  );
  return { close: () => stop.abort() };
}
