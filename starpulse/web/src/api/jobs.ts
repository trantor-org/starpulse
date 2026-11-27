// The jobs the Jobs page lists: one POST /api/jobs read, then the jobChanges subscription on POST /graphql from the position it returned.

import { apiFetch } from "./apiFetch";
import { follow, type Ended, type Post } from "./subscribe";
import type { Dag, Jobs } from ".";

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
const DOMAINS = "domains { name dags { name } processes { name dags { name } } } cues { dag event state on resolves grace } pools { name cap running queued }";
const SUBSCRIPTION = `subscription ($from: Int!) { jobChanges(from: $from) { jobs { ${JOB_FIELDS} } error ${DOMAINS} } }`;

/** How long the one read may take, its body included, before it rejects and `useJobs` retries. */
const READ_TIMEOUT_MS = 30_000;

export async function readJobs(post: Post = apiFetch): Promise<Jobs | null> {
  const resp = await post("/api/jobs", { method: "POST", body: "{}", signal: AbortSignal.timeout(READ_TIMEOUT_MS) });
  return resp.ok ? ((await resp.json()) as Jobs) : null;
}

/** What a change hands over beside the job list: the domains, the cues and the pools, whole. */
export type JobsBeside = Pick<Jobs, "domains" | "cues" | "pools">;

/** Each change after `from` hands over the full job list, the runs error and what rides beside them; `end` says why the stream stopped, unless `close` stopped it. */
export function followJobs(
  from: number,
  on: { jobs(list: Dag[], error: string | null, beside: JobsBeside): void; end(why: Ended): void },
  post: Post = apiFetch,
): { close(): void } {
  return follow<{ jobs: Dag[]; error: string | null } & JobsBeside>(SUBSCRIPTION, "jobChanges", from, { change: (c) => on.jobs(c.jobs, c.error, c), end: on.end }, post);
}
