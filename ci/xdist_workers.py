"""Print the pytest-xdist worker count a validate runner's memory limit can hold.

An Unraid farm slot is capped at 4 GiB, and its cgroup also holds its own dockerd and the Postgres containers the
hub tests start; a worker OOM-killed there leaves xdist hanging until the job timeout. So a memory-limited runner gets
one worker per 2 GiB. A runner with no cgroup memory limit shares ai-vm-1's cores with the rest of the pool and gets
MAX_WORKERS. trantor's `bin/ci_pytest_workers.py` applies the same rule to its own Validate job.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_WORKERS = 4
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
