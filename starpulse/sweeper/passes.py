"""One sweeper pass: each kind in order, then the housekeeping, with the counts kept as metrics and one journal line."""

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from starpulse.event_log.kept_text import kept_state

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

HOUSEKEEPING = "housekeeping:"
PROGRESS = "sweeper.progress"


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


@runtime_checkable
class Exposes(Protocol):
    """A kind that keeps Prometheus series of its own beyond the sweeper's counts."""

    def exposition(self) -> str: ...


def kind_series(kinds: Sequence[Kind]) -> str:
    """The series of each kind that keeps its own, joined."""
    return "".join(kind.exposition() for kind in kinds if isinstance(kind, Exposes))


class Progress:
    """The steps the pass under way has finished, kept in the event log, so a worker a reload replaces mid-pass leaves the
    next worker to resume that pass rather than start it over; a pass begun `interval_s` or more ago starts over."""

    def __init__(self, log: EventLog, interval_s: float) -> None:
        self._log = log
        self._interval_s = interval_s
        self._started = 0.0
        self._done: list[str] = []

    def begin(self, now: float) -> frozenset[str]:
        """Start a pass at `now`, or resume the one a replaced worker left; return the steps it already finished."""
        kept = kept_state(self._log, PROGRESS)()
        if kept and now - kept["started"] < self._interval_s:
            self._started, self._done = kept["started"], list(kept["done"])
        else:
            self._started, self._done = now, []
        return frozenset(self._done)

    def ran(self, step: str) -> None:
        self._done.append(step)
        self._keep({"started": self._started, "done": self._done})

    def end(self) -> None:
        self._keep({})

    def _keep(self, state: dict[str, Any]) -> None:
        try:
            self._log.put_state(PROGRESS, state)
        except Exception:
            logger.warning("sweeper: the pass progress was not kept", exc_info=True)


def run_pass(
    kinds: Sequence[Kind],
    housekeeping: Sequence[Housekeeping],
    metrics: Metrics,
    clock: Callable[[], float] = time.time,
    progress: Progress | None = None,
) -> None:
    """Run every kind in order, then every housekeeping step; one that raises is logged and counted as an error, and the
    rest still run. With `progress`, a step the resumed pass already finished is skipped. Writes one INFO line naming each
    kind and its corrections (`error` for one that raised, `earlier` for one skipped)."""
    done = progress.begin(clock()) if progress else frozenset()
    ran = progress.ran if progress else lambda _step: None
    said = []
    for kind in kinds:
        if kind.name in done:
            said.append(f"{kind.name}=earlier")
            continue
        try:
            outcome = kind.run()
        except Exception:
            logger.exception("sweeper: kind %s failed", kind.name)
            metrics.failed(kind.name)
            said.append(f"{kind.name}=error")
        else:
            metrics.counted(kind.name, outcome)
            said.append(f"{kind.name}={outcome.corrected}")
        ran(kind.name)
    for step in housekeeping:
        if HOUSEKEEPING + step.name in done:
            continue
        try:
            step.run()
        except Exception:
            logger.exception("sweeper: housekeeping %s failed", step.name)
            metrics.failed(HOUSEKEEPING + step.name)
        ran(HOUSEKEEPING + step.name)
    if progress:
        progress.end()
    number = metrics.pass_done(clock())
    logger.info("sweeper: pass %d: %s", number, " ".join(said))
