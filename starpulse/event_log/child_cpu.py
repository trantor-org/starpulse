"""`starpulse_child_cpu_seconds_total{child}`: CPU seconds of the Page API process and of the `contexts` and `conformance` children.

Each of those children keeps its pid and start time once, at start; the Page API reads that process's CPU time at each
scrape, so no timer samples it and the series is never stale. A child that is gone or replaced under the kept
pid leaves its sample out.
"""

import logging
from collections.abc import Callable

import psutil

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_state

logger = logging.getLogger(__name__)

STATE = "contexts.process"
#: The state each child keeps its process under.
STATES = {"contexts": STATE, "conformance": "conformance.process"}
NAME = "starpulse_child_cpu_seconds_total"


def keep_process(log: EventLog, child: str = "contexts") -> None:
    """Keep this process's pid and start time as the `child` for the Page API; a log that cannot be written is logged."""
    me = psutil.Process()
    try:
        log.put_state(STATES[child], {"pid": me.pid, "created": me.create_time()})
    except Exception:
        logger.warning("%s: the process was not kept for the CPU metric", child, exc_info=True)


def _cpu(process: psutil.Process) -> float:
    times = process.cpu_times()
    return times.user + times.system


def _kept_cpu(kept: dict) -> float | None:
    try:
        process = psutil.Process(kept["pid"])
        return _cpu(process) if process.create_time() == kept["created"] else None
    except psutil.Error, KeyError, TypeError:
        return None


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The CPU seconds of this process as `api` and of each kept child process, read now."""
    kept = {child: kept_state(log, state) for child, state in STATES.items()}

    def read() -> str:
        samples = {"api": _cpu(psutil.Process()), **{child: _kept_cpu(state()) for child, state in kept.items()}}
        lines = [f'{NAME}{{child="{child}"}} {cpu}' for child, cpu in samples.items() if cpu is not None]
        header = f"# HELP {NAME} CPU seconds of a StarPulse child process, user plus system\n# TYPE {NAME} counter\n"
        return header + "\n".join(lines) + "\n"

    return read
