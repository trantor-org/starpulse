"""Every task a session holds In Progress counts against the sessions limit, idle on a wake or mid-turn."""

from __future__ import annotations

from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.model.harness import SESSION_MACHINES
from starpulse.scheduler.adapters.runtime import Runtime, build
from starpulse.scheduler.model.config import Scheduler
from tests.machines import MACHINES, ROLES

HELD = 30


def _task(task: str, lane: str) -> BoardTask:
    return BoardTask(id=task, team="demo", title=task, lane=lane, labels=["size-1"], profile="@agent-standard-high")


def _runtime(tmp_path: Path, started: list[str]) -> tuple[Runtime, BoardFeed]:
    """A scheduler with the sessions limit at `HELD`, cpu and memory idle, over `HELD` idle In Progress tasks and a Ready one."""
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    for number in range(HELD):
        feed.put(_task(f"H-{number}", "in_progress"))  # no harness event: its session ended its turn on a wake
    feed.put(_task("R-1", "ready"))

    def start(task: str, **_: object) -> str:
        started.append(task)
        return f"https://claude.ai/code/{task}"

    runtime = build(
        Scheduler(lane="ready", limits={**Scheduler().limits, "sessions": HELD}),
        EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"),
        feed,
        probe=lambda: {"cpu": 5.0, "memory": 5.0},
        start=start,
        settle=lambda task, reason: Written(True, task),
        lane="ready",
    )
    runtime.set_enabled(True)
    runtime.sampler.sample()
    return runtime, feed


def test_idle_in_progress_tasks_are_the_sessions_use(tmp_path: Path) -> None:
    runtime, _ = _runtime(tmp_path, [])

    readings, _ = runtime.sampler.readings()

    assert {reading.name: reading.use for reading in readings}["sessions"] == HELD


def test_a_full_sessions_limit_of_idle_in_progress_tasks_admits_no_ready_task(tmp_path: Path) -> None:
    started: list[str] = []
    runtime, _ = _runtime(tmp_path, started)
    assert runtime.loop is not None

    assert runtime.loop.tick() == []
    assert started == []
    assert runtime.loop.sessions_by_harness()["claude"] == {"use": float(HELD), "limit": float(HELD)}
