"""Admission retries a refusal on a capacity event only: a pressure crossing or a session ending, never an unrelated event."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.harness_telemetry.model.harness import HARNESS, SESSION_MACHINES
from starpulse.scheduler.adapters.pressure import watch
from starpulse.scheduler.adapters.runtime import build
from starpulse.scheduler.model.config import Scheduler
from starpulse.scheduler.model.sampler import Sampler

from tests.machines import MACHINES, ROLES


def _refused_loop(tmp_path: Path):
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    feed.put(
        BoardTask(id="T-1", team="demo", title="T-1", lane="ready", labels=["size-8"], profile="@agent-standard-high")
    )
    host = {"cpu": 95.0, "memory": 5.0}
    runtime = build(
        Scheduler(lane="ready"),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: host,
        start=lambda task, **_: f"https://claude.ai/code/{task}",
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    assert runtime.loop is not None
    runtime.set_enabled(True)
    runtime.sampler.sample()
    assert runtime.loop.tick() == []  # refused: CPU is full
    return runtime.loop


def _ready(task: str) -> dict:
    return {"id": task, "agent": {"id": task, "state": "ready", "labels": []}}


def test_an_unrelated_event_does_not_retry_a_refusal_but_a_capacity_event_does(tmp_path: Path) -> None:
    loop = _refused_loop(tmp_path)

    assert not loop.wants("task", _ready("T-1"))  # an edit to the refused task
    assert not loop.wants("task", _ready("T-2"))  # a new Ready task cannot fit while capacity is full
    assert loop.wants("wake", {})  # a pressure crossing wakes admission
    assert loop.wants("task", _ready("T-2"))  # the crossing reopened admission


def test_a_session_ending_wakes_admission_after_a_refusal(tmp_path: Path) -> None:
    loop = _refused_loop(tmp_path)

    stopped = {"id": "T-9", "machine": HARNESS.name, "agent": {"state": "stopped"}}

    assert loop.wants("move", stopped)
    assert loop.wants("task", _ready("T-2"))


def test_the_sampler_samples_again_only_when_woken() -> None:
    samples: list[float] = []
    sampler = Sampler(
        limits=lambda: {"cpu": 80.0},
        probe=lambda: samples.append(1.0) or {"cpu": 10.0},
        sessions=lambda: 0.0,
        review=lambda: 0.0,
        on_crossing=lambda crossing: None,
        clock=time.time,
    )
    stop, wake = StopEvent(), threading.Event()
    thread = threading.Thread(target=sampler.run_forever, args=(stop, wake), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while len(samples) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.2)
        assert len(samples) == 1  # the baseline, then silence

        wake.set()
        deadline = time.monotonic() + 5
        while len(samples) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(samples) == 2
    finally:
        stop.set()
        wake.set()
        thread.join(5)


def test_a_host_without_pressure_files_gets_no_watcher() -> None:
    assert watch(threading.Event(), threading.Event(), files=("/proc/pressure/none",)) is None


@pytest.mark.skipif(not Path("/proc/pressure/cpu").exists(), reason="the kernel has no PSI")
def test_the_watcher_ends_with_stop() -> None:
    stop = threading.Event()
    thread = watch(stop, threading.Event())
    assert thread is not None

    stop.set()
    thread.join(5)

    assert not thread.is_alive()
