"""Print the pytest-xdist worker count a self-hosted runner's memory limit can hold.

A runner whose cgroup is capped also holds the Postgres containers the hub tests start in that cap; a worker
OOM-killed there leaves xdist hanging until the job timeout. So a memory-limited runner gets one worker per 2 GiB. A runner with no cgroup memory limit shares the build host's cores with the rest of the pool and gets
MAX_WORKERS: two, so a pool of runners fills the host's test CPU budget instead of oversubscribing it. trantor's
`bin/ci_pytest_workers.py` applies the same rule to its own Validate job.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_WORKERS = 2
GIB_PER_WORKER = 2
CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")


def workers_for(limit: str) -> int:
    try:
        limit_bytes = int(limit)
    except ValueError:  # "max" (unlimited) or empty
        return MAX_WORKERS
    return max(1, min(MAX_WORKERS, limit_bytes // (GIB_PER_WORKER * 1024**3)))


def workers_for_file(path: Path) -> int:
    try:
        return workers_for(path.read_text().strip())
    except OSError:  # no cgroup v2 memory limit file
        return MAX_WORKERS


if __name__ == "__main__":
    print(workers_for_file(Path(sys.argv[1]) if len(sys.argv) > 1 else CGROUP_MEMORY_MAX))
