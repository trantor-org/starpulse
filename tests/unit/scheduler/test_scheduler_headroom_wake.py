"""A Ready task refused for headroom, with no dimension full, starts once a sample leaves room, with nothing else running."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.model.harness import SESSION_MACHINES
from starpulse.scheduler.adapters.runtime import build
from starpulse.scheduler.model.config import Scheduler

from tests.machines import MACHINES, ROLES

DEADLINE_S = 10.0


def _until(condition: Callable[[], object], what: str) -> None:
    end = time.monotonic() + DEADLINE_S
    while not condition():
        if time.monotonic() > end:
            pytest.fail(f"{what} did not happen within {DEADLINE_S:g}s")
        time.sleep(0.02)


def test_a_task_refused_for_headroom_starts_when_a_sample_leaves_room_with_nothing_in_progress(tmp_path: Path) -> None:
    # A size-8 standard task prices 16 percent of CPU: at 70 of 80 it is refused though CPU is not full, and at 10 it fits.
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    feed.put(
        BoardTask(id="T-1", team="demo", title="T-1", lane="ready", labels=["size-8"], profile="@agent-standard-high")
    )
    host = {"cpu": 70.0, "memory": 5.0}
    started: list[str] = []

    def start(task: str, **_: object) -> str:
        started.append(task)
        return f"https://claude.ai/code/{task}"

    runtime = build(
        Scheduler(lane="ready"),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: host,
        start=start,
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    assert runtime.loop is not None
    runtime.wire_status(feed.publish)
    runtime.set_enabled(True)
    runtime.sampler.sample()  # the baseline
    _, changes = feed.subscribe()
    stop = threading.Event()
    thread = threading.Thread(target=runtime.loop.run_forever, args=(stop,), daemon=True)
    thread.start()
    try:
        _until(lambda: _saw(changes, "scheduler"), "the loop's first tick")
        assert started == []  # refused for CPU headroom, not started

        host["cpu"] = 10.0
        runtime.sampler.sample()

        _until(lambda: started, "the start after the sample left room")
        assert started == ["T-1"]
    finally:
        stop.set()
        runtime.loop.wake()
        thread.join(DEADLINE_S)


def _saw(changes: queue.Queue, kind: str) -> bool:
    while True:
        try:
            if changes.get_nowait()[0] == kind:
                return True
        except queue.Empty:
            return False
