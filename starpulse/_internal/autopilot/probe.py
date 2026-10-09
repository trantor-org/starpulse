"""The built-in host probe: CPU and memory use in percent, read from `/proc`, so a fresh install needs no monitoring stack.

A probe is any zero-argument callable that answers `{"cpu": percent, "memory": percent}`; the sampler takes another in its place.
"""

from pathlib import Path


class LocalProbe:
    """Reads the host's CPU and memory from `proc` (Linux `/proc`).

    CPU is the busy share of the ticks since the previous call, and since boot for the first; a call with no ticks since
    the last repeats its answer.
    """

    def __init__(self, proc: Path = Path("/proc")) -> None:
        self.proc = proc
        self._ticks: tuple[int, int] | None = None  # (busy, total) at the previous call
        self._cpu = 0.0

    def __call__(self) -> dict[str, float]:
        return {"cpu": self._cpu_percent(), "memory": self._memory_percent()}

    def _cpu_percent(self) -> float:
        user, nice, system, idle, iowait, *rest = map(int, (self.proc / "stat").read_text().split("\n", 1)[0].split()[1:])
        total = user + nice + system + idle + iowait + sum(rest)
        busy = total - idle - iowait
        before_busy, before_total = self._ticks or (0, 0)
        self._ticks = busy, total
        if total > before_total:
            self._cpu = 100 * (busy - before_busy) / (total - before_total)
        return self._cpu

    def _memory_percent(self) -> float:
        kb = {
            name: int(value.split()[0])
            for name, _, value in (line.partition(":") for line in (self.proc / "meminfo").read_text().splitlines())
        }
        return 100 * (kb["MemTotal"] - kb["MemAvailable"]) / kb["MemTotal"]
