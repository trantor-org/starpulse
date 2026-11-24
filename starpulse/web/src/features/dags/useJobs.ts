// The jobs the Jobs page lists: read once, then followed by the jobs subscription. A stream that ends is read and followed again; a position the server no longer holds at once.

import { useEffect, useState } from "react";
import { apiFetch } from "../../api/apiFetch";
import { followJobs, readJobs } from "../../api/jobs";
import { keep } from "../../api/same";
import type { Dag } from "../../api";

const RETRY_MS = 3000;

export function useJobs(on: boolean, post: typeof apiFetch = apiFetch): { jobs: Dag[] | null; error: string | null } {
  const [state, set] = useState<{ jobs: Dag[] | null; error: string | null }>({ jobs: null, error: null });
  useEffect(() => {
    if (!on) return;
    let dead = false, retry: ReturnType<typeof setTimeout> | undefined, follow: { close(): void } | undefined;
    const take = (jobs: Dag[], error: string | null) => set((prev) => ({ jobs: prev.jobs ? keep(prev.jobs, jobs, (d: Dag) => d.name) : jobs, error }));
    const connect = async () => {
      const read = await readJobs(post).catch(() => null);
      if (dead) return;
      if (!read) { retry = setTimeout(() => void connect(), RETRY_MS); return; }
      take(read.items, read.error ?? null);
      follow = followJobs(read.position, { jobs: take, end: (why) => { retry = setTimeout(() => void connect(), why === "reread" ? 0 : RETRY_MS); } }, post);
    };
    void connect();
    return () => { dead = true; clearTimeout(retry); follow?.close(); };
  }, [on, post]);
  return state;
}
