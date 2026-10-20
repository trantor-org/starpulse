"""Print the pytest-xdist worker count a self-hosted runner's memory limit can hold.

A runner whose cgroup is capped also holds the Postgres containers the tests start in that cap; a worker
OOM-killed there leaves xdist hanging until the job timeout. So a memory-limited runner gets one worker per 2 GiB. A runner with no cgroup memory limit shares the build host's cores with the rest of the pool and gets
MAX_WORKERS: two, so a pool of runners fills the host's test CPU budget instead of oversubscribing it. trantor's
`bin/ci_pytest_workers.py` applies the same rule to its own Validate job.

`--slice` prints the count for the build host's `tests.slice` instead: one pytest session of work-stealing workers
(`--dist worksteal`) under that slice's MemoryHigh, sized from the peak RSS measured below.
"""

from __future__ import annotations

import sys
from pathlib import Path

MAX_WORKERS = 2
GIB_PER_WORKER = 2
CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")

#: Peak resident memory of one worker and the processes it starts (subprocess servers), in MiB, rounded up from
#: the largest of eight full-suite sessions at `-n 12`, `-n 16` and `-n 17 --dist worksteal` on the build host
#: (TASK-6307): 1128, 1099, 1108, 1234, 1100, 1303, 1152 and 1139 MiB per worker subtree. Only the first six workers
#: reach it; the whole 16-worker tree peaked at 7.1-8.7 GiB, so the bound is conservative. Docker containers sit
#: outside the tree (the one shared Postgres) and count against the slice too.
PEAK_WORKER_RSS_MIB = 1350
#: `tests.slice`'s MemoryHigh on the build host: past it the slice is throttled (23,847 MemoryHigh events).
SLICE_MEMORY_HIGH_GIB = 20


def workers_for(limit: str) -> int:
    try:
        limit_bytes = int(limit)
    except ValueError:  # "max" (unlimited) or empty
        return MAX_WORKERS
    return max(1, min(MAX_WORKERS, limit_bytes // (GIB_PER_WORKER * 1024**3)))


def slice_workers(peak_mib: int, high_gib: int) -> int:
    """Workers whose peaks, all landing together, still fit inside the slice's MemoryHigh."""
    return max(1, high_gib * 1024 // peak_mib)


SLICE_WORKERS = slice_workers(PEAK_WORKER_RSS_MIB, SLICE_MEMORY_HIGH_GIB)


def workers_for_file(path: Path) -> int:
    try:
        return workers_for(path.read_text().strip())
    except OSError:  # no cgroup v2 memory limit file
        return MAX_WORKERS


if __name__ == "__main__":
    if sys.argv[1:] == ["--slice"]:
        print(SLICE_WORKERS)
        raise SystemExit
    print(workers_for_file(Path(sys.argv[1]) if len(sys.argv) > 1 else CGROUP_MEMORY_MAX))
