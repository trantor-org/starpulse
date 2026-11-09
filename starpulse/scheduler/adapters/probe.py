"""The built-in host probe: CPU and memory use in percent, read through psutil, so a fresh install needs no monitoring stack.

A probe is any zero-argument callable that answers `{"cpu": percent, "memory": percent}`; the sampler takes another in its place.
"""

import psutil


class LocalProbe:
    """Reads the host's CPU and memory with psutil.

    CPU is the busy share of the ticks since the previous call, and since construction for the first.
    """

    def __init__(self) -> None:
        psutil.cpu_percent(interval=None)  # psutil measures from the previous call; the first has none to measure from

    def __call__(self) -> dict[str, float]:
        return {"cpu": psutil.cpu_percent(interval=None), "memory": psutil.virtual_memory().percent}
