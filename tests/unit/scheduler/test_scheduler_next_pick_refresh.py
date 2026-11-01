"""The served next pick follows the lane: a task entering Ready after an empty pick shows without a sample or switch change."""

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


def test_a_task_entering_ready_after_an_empty_pick_is_the_served_next_pick(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    runtime = build(
        Scheduler(lane="ready"),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: {"cpu": 10.0, "memory": 5.0},
        start=lambda task, **_: f"https://claude.ai/code/{task}",
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    assert runtime.loop is not None
    runtime.wire_status(feed.publish)
    runtime.sampler.sample()
    assert runtime.served_status()["next"] is None
    stop = threading.Event()
    thread = threading.Thread(target=runtime.loop.run_forever, args=(stop,), daemon=True)
    thread.start()
    try:
        feed.put(BoardTask(id="T-1", team="demo", title="T-1", lane="ready", labels=[], profile="@agent-standard-medium"))

        _until(lambda: (runtime.served_status()["next"] or {}).get("task") == "T-1", "the next pick showing T-1")
    finally:
        stop.set()
        runtime.loop.wake()
        thread.join(DEADLINE_S)


def test_a_tick_that_raises_still_pushes_the_status(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    runtime = build(
        Scheduler(lane="ready"),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: {"cpu": 10.0, "memory": 5.0},
        start=lambda task, **_: f"https://claude.ai/code/{task}",
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    assert runtime.loop is not None

    def failing(*_: object, **__: object) -> list[str]:
        raise RuntimeError("tick failed")

    runtime.loop.tick = failing  # type: ignore[method-assign]
    runtime.wire_status(feed.publish)
    _, changes = feed.subscribe()

    with pytest.raises(RuntimeError):
        runtime.loop.tick()

    kinds = []
    while True:
        try:
            kinds.append(changes.get_nowait()[0])
        except queue.Empty:
            break
    assert "scheduler" in kinds
