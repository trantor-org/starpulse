"""The server process's own resident memory, CPU time, threads, open files and start time, as Prometheus metrics."""

import psutil
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client.process_collector import ProcessCollector

REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)  # `process_*` gauges as Prometheus's client libraries name them; none on a host without procfs
# `psutil.Process()` per call, so a forked worker counts its own threads, not the preloading parent's.
Gauge("process_threads", "Number of OS threads in the process.", registry=REGISTRY).set_function(
    lambda: psutil.Process().num_threads()
)


def process_gauges() -> str:
    """The Prometheus text of this process's `process_*` gauges."""
    return generate_latest(REGISTRY).decode()
