"""The server process's own resident memory, threads, open files and start time, as Prometheus gauges."""

import os
import time
from pathlib import Path

#: When this process began serving, so a restart moves `process_start_time_seconds` and a growth rule can tell one
#: process lifetime from the next.
STARTED = time.time()


def process_gauges(proc: Path = Path("/proc/self"), *, started: float = STARTED) -> str:
    """The `process_*` gauges Prometheus's client libraries name, read from `proc`; none where it has no such files."""
    try:
        resident_pages = int((proc / "statm").read_text().split()[1])
        threads = next(
            int(line.split()[1]) for line in (proc / "status").read_text().splitlines() if line.startswith("Threads:")
        )
        open_fds = len(os.listdir(proc / "fd"))
    except OSError, IndexError, StopIteration, ValueError:
        return ""
    gauges = [
        (
            "process_resident_memory_bytes",
            "Resident memory size in bytes.",
            resident_pages * os.sysconf("SC_PAGE_SIZE"),
        ),
        ("process_threads", "Number of OS threads in the process.", threads),
        ("process_open_fds", "Number of open file descriptors.", open_fds),
        ("process_start_time_seconds", "Start time of the process since the Unix epoch in seconds.", started),
    ]
    return "".join(f"# HELP {name} {help_}\n# TYPE {name} gauge\n{name} {value}\n" for name, help_, value in gauges)
