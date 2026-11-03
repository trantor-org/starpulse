"""One sweeper pass: each kind in order, then the housekeeping, with the counts kept as metrics and one journal line."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)

HOUSEKEEPING = "housekeeping:"


@dataclass(frozen=True)
class Outcome:
    """What a kind did in one pass: the entries it `sampled` and how many of them it `corrected`."""

    corrected: int = 0
    sampled: int = 0


class Kind(Protocol):
    """One kind of correction the sweeper counts: `run` looks, corrects what it finds and says how many; it may raise."""

    name: str

    def run(self) -> Outcome: ...


class Housekeeping(Protocol):
    """A step the pass runs after the kinds and does not count: `run` may raise."""

    name: str

    def run(self) -> None: ...


@dataclass(frozen=True)
class Step:
    """A housekeeping step made of a callable."""

    name: str
    run: Callable[[], object]


class Metrics:
    """The sweeper's counters; `exposition` is their Prometheus text."""

    def __init__(self, kinds: Sequence[str]) -> None:
        self._lock = threading.Lock()
        self._passes = 0
        self._last = 0.0
        self._corrections = dict.fromkeys(kinds, 0)
        self._samples = dict.fromkeys(kinds, 0)
        self._errors = dict.fromkeys(kinds, 0)

    def pass_done(self, at: float) -> int:
        with self._lock:
            self._passes += 1
            self._last = at
            return self._passes

    def counted(self, kind: str, outcome: Outcome) -> None:
        with self._lock:
            self._corrections[kind] = self._corrections.get(kind, 0) + outcome.corrected
            self._samples[kind] = self._samples.get(kind, 0) + outcome.sampled

    def failed(self, kind: str) -> None:
        with self._lock:
            self._errors[kind] = self._errors.get(kind, 0) + 1

    def exposition(self) -> str:
        with self._lock:
            lines = [
                "# HELP starpulse_sweeper_passes_total Sweeper passes completed.",
                "# TYPE starpulse_sweeper_passes_total counter",
                f"starpulse_sweeper_passes_total {self._passes}",
                "# HELP starpulse_sweeper_last_pass_timestamp_seconds When the last sweeper pass ended.",
                "# TYPE starpulse_sweeper_last_pass_timestamp_seconds gauge",
                f"starpulse_sweeper_last_pass_timestamp_seconds {self._last}",
            ]
            series = (
                ("corrections", "Entries a kind corrected.", self._corrections),
                ("samples", "Entries a kind looked at.", self._samples),
                ("pass_errors", "Passes in which a kind or housekeeping step raised.", self._errors),
            )
            for name, help_text, counts in series:
                lines += [f"# HELP starpulse_sweeper_{name}_total {help_text}", f"# TYPE starpulse_sweeper_{name}_total counter"]
                lines += [f'starpulse_sweeper_{name}_total{{kind="{kind}"}} {count}' for kind, count in counts.items()]
        return "\n".join(lines) + "\n"


def run_pass(
    kinds: Sequence[Kind],
    housekeeping: Sequence[Housekeeping],
    metrics: Metrics,
    clock: Callable[[], float] = time.time,
) -> None:
    """Run every kind in order, then every housekeeping step; one that raises is logged and counted as an error, and the
    rest still run. Writes one INFO line naming each kind and its corrections (`error` for one that raised)."""
    said = []
    for kind in kinds:
        try:
            outcome = kind.run()
        except Exception:
            logger.exception("sweeper: kind %s failed", kind.name)
            metrics.failed(kind.name)
            said.append(f"{kind.name}=error")
        else:
            metrics.counted(kind.name, outcome)
            said.append(f"{kind.name}={outcome.corrected}")
    for step in housekeeping:
        try:
            step.run()
        except Exception:
            logger.exception("sweeper: housekeeping %s failed", step.name)
            metrics.failed(HOUSEKEEPING + step.name)
    number = metrics.pass_done(clock())
    logger.info("sweeper: pass %d: %s", number, " ".join(said))
