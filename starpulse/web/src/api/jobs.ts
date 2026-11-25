// The jobs the Jobs page lists: one POST /api/jobs read, then the jobChanges subscription on POST /graphql from the position it returned.

import { apiFetch } from "./apiFetch";
import { frames } from "./sse";
import type { Dag, Jobs } from ".";

type Post = (url: string, init?: RequestInit) => Promise<Response>;

const RUN = "runId url status raw startedAt steps task pr commit attempt failure";
const JOB_FIELDS = [
  "name status raw runId startUrl startedAt finishedAt schedule pool",
  "steps { name depends status raw kind precondition lock last }",
  "stats { runs hours medianSeconds p95Seconds failureShare }",
  "rerun { key repeats step }",
  `active { ${RUN} step stepStartedAt }`,
  `failed { ${RUN} finishedAt params }`,
  `closed { ${RUN} finishedAt params }`,
].join(" ");
const SUBSCRIPTION = `subscription ($from: Int!) { jobChanges(from: $from) { jobs { ${JOB_FIELDS} } error } }`;

/** Why a subscription ended: the server closed it, or the position it held is gone and the list must be read again. */
export type Ended = "closed" | "reread";

/** How long the one read may take, its body included, before it rejects and `useJobs` retries. */
const READ_TIMEOUT_MS = 30_000;

export async function readJobs(post: Post = apiFetch): Promise<Jobs | null> {
  const resp = await post("/api/jobs", { method: "POST", body: "{}", signal: AbortSignal.timeout(READ_TIMEOUT_MS) });
  return resp.ok ? ((await resp.json()) as Jobs) : null;
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
