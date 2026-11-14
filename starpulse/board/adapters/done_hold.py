"""Keeps today's Done tasks in `tasks/` until their local day ends, with a fallback to full dehydration when that slows the board."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from starpulse.board.model.seam import Written
from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)

METRIC = "starpulse_board_done_hold_fallback"
HELP = "1 while the board dehydrates every Done task because keeping today's slowed it, until its complete_hold table changes."
MARKER = "done-hold-fallback.json"
INTERVAL = 15.0
SCRAPE_S = 5.0
READS = 5
_BUCKET = r'^{metric}_bucket{{le="([^"]+)"}} (\S+)$'

DoneFiles = Callable[[], list[tuple[str, Path]]]


def p95(samples: list[float]) -> float:
    """The 95th-percentile of `samples`, nearest rank."""
    ordered = sorted(samples)
    return ordered[max(math.ceil(0.95 * len(ordered)) - 1, 0)]


def buckets(text: str, metric: str) -> dict[float, float]:
    """`{upper bound: cumulative count}` of the histogram `metric` in Prometheus text."""
    pattern = re.compile(_BUCKET.format(metric=re.escape(metric)), re.M)
    return {float(bound): float(count) for bound, count in pattern.findall(text)}


def histogram_p95(before: Mapping[float, float], after: Mapping[float, float]) -> float | None:
    """The upper bound of the bucket holding the 95th percentile of what `after` counted past `before`; none when nothing was."""
    delta = {bound: count - before.get(bound, 0.0) for bound, count in after.items()}
    total = delta.get(math.inf, 0.0)
    if total <= 0:
        return None
    return next(bound for bound, count in sorted(delta.items()) if count >= 0.95 * total)


def _marker(root: Path) -> dict[str, Any]:
    try:
        marker = json.loads((root / MARKER).read_text())
    except (OSError, ValueError):
        return {}
    return marker if isinstance(marker, dict) else {}


def exposition(root: Path) -> str:
    """Prometheus text of the gauge: one series while a fallback marker is on the board, none otherwise."""
    marker = _marker(root)
    reason = str(marker.get("reason", "")).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    series = f'{METRIC}{{reason="{reason}"}} 1\n' if marker else ""
    return f"# HELP {METRIC} {HELP}\n# TYPE {METRIC} gauge\n{series}"


class DoneHold:
    """Decides whether a task landing in Done is dehydrated now, sweeps the ones whose day ended, and watches for the fallback."""

    def __init__(
        self,
        root: Path,
        done_files: DoneFiles,
        complete: Callable[[str], Written],
        settings: Mapping[str, Any] | None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        table = dict(settings or {})
        self._root, self._done_files, self._complete, self._clock = root, done_files, complete, clock
        self._zone = ZoneInfo(str(table["tz"])) if table.get("tz") else None
        self._forced = bool(table.get("fallback", False))
        self._p95_s = float(table.get("p95_seconds", 1.0))
        self._baseline = float(table.get("p95_baseline", 0.0))
        self._ratio = float(table.get("p95_ratio", 1.2))
        self._actor_s = float(table.get("actor_seconds", 60.0))
        self._sustained = float(table.get("sustained", 600.0))
        self._url = str(table.get("actor_metrics", ""))
        self._fingerprint = hashlib.sha256(json.dumps(table, sort_keys=True, default=str).encode()).hexdigest()[:16]
        self._since: dict[str, float] = {}
        self._swept_day = -1.0

    def holds(self) -> bool:
        """Whether a Done task stays in `tasks/` for the rest of its local day."""
        marker = _marker(self._root)
        if marker and marker.get("settings") != self._fingerprint:
            (self._root / MARKER).unlink(missing_ok=True)  # an edited table ends the fallback, and its gauge
            marker = {}
        return self._zone is not None and not self._forced and not marker

    def _day_start(self) -> float:
        local = datetime.fromtimestamp(self._clock(), self._zone)
        return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def landed(self, task: str) -> None:
        """Dehydrate `task`, a Done move just landed, unless today's Done tasks are kept."""
        if not self.holds():
            self._complete(task)

    def sweep(self) -> list[str]:
        """Dehydrate each Done task in `tasks/` whose day ended (all of them without the hold); the ids moved."""
        cutoff = self._day_start() if self.holds() else math.inf
        moved = []
        for task, path in self._done_files():
            try:
                written = path.stat().st_mtime < cutoff and self._complete(task).ok
            except OSError:
                continue  # moved while looking
            if written:
                moved.append(task)
        self._swept_day = self._day_start() if self._zone else -1.0
        return moved

    def _breached(self, signal: str, seconds: float | None) -> bool | None:
        if seconds is None:
            return None
        if signal == "actor":
            return seconds > self._actor_s
        return seconds > self._p95_s or bool(self._baseline and seconds > self._baseline * self._ratio)

    def observe(self, board_s: float | None, actor_s: float | None) -> str:
        """Count the samples (seconds; none: unmeasured); the reason the fallback tripped on them, or empty."""
        now = self._clock()
        for signal, seconds in (("board", board_s), ("actor", actor_s)):
            breached = self._breached(signal, seconds)
            if breached is None:
                continue
            if not breached:
                self._since.pop(signal, None)
                continue
            began = self._since.setdefault(signal, now)
            if now - began >= self._sustained and self.holds():
                return self._trip(signal, seconds or 0.0)
        return ""

    def _trip(self, signal: str, seconds: float) -> str:
        reason = f"{signal} {seconds:.2f}s past its threshold for {self._sustained:.0f}s"
        record = {"at": self._clock(), "reason": reason, "settings": self._fingerprint}
        staged = self._root / f"{MARKER}.tmp"
        staged.write_text(json.dumps(record))
        staged.replace(self._root / MARKER)
        logger.error("StarPulse: Done tasks are dehydrated on landing again, %s: edit [board.complete_hold] to hold them", reason)
        self.sweep()
        return reason

    def _board_read_s(self, read: Callable[[], object]) -> float:
        times = []
        for _ in range(READS):
            began = time.perf_counter()
            read()
            times.append(time.perf_counter() - began)
        return p95(times)

    def _scrape(self) -> dict[float, float] | None:
        if not self._url.startswith(("http://", "https://")):
            return None
        try:
            with urllib.request.urlopen(self._url, timeout=SCRAPE_S) as response:  # noqa: S310 — the operator's own metrics URL
                return buckets(response.read().decode(), "starpulse_task_actor_latency_seconds")
        except (OSError, ValueError) as exc:
            logger.warning("StarPulse: the done hold could not read %s: %s", self._url, exc)
            return None

    def start(self, stopped: StopEvent, read: Callable[[], object]) -> None:
        """On a daemon thread every `INTERVAL` seconds: sweep once a local day, and sample `read` (a board read) and the actor."""
        if self._zone is None:
            return
        threading.Thread(target=self._run, args=(stopped, read), name="done-hold", daemon=True).start()

    def _run(self, stopped: StopEvent, read: Callable[[], object]) -> None:
        before = self._scrape() or {}
        while not stopped.wait(INTERVAL):
            try:
                if self._day_start() != self._swept_day:
                    self.sweep()
                after = self._scrape()
                actor = histogram_p95(before, after) if after is not None else None
                before = after if after is not None else before
                self.observe(self._board_read_s(read), actor)
            except Exception as exc:  # a file or the metrics are unreadable; the next pass tries again
                logger.warning("StarPulse: the done hold failed: %s", exc)
