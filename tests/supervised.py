"""Read a test Supervisor's children: the pid of each one running now."""

from starpulse.runtime.supervisor import Supervisor


def running_pids(supervisor: Supervisor) -> dict[str, int]:
    with supervisor._lock:
        return {n: c.proc.pid for n, c in supervisor._children.items() if c.proc is not None and c.proc.poll() is None}
