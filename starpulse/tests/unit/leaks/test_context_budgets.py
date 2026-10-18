"""Each background context holds no more than its declared budget after a fixed workload of its own loop."""

from __future__ import annotations

from collections.abc import Callable
from itertools import cycle
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.autopilot.ledger import Ledger
from starpulse._internal.autopilot.loop import Loop
from starpulse._internal.autopilot.sampler import Sampler
from starpulse._internal.autopilot.toggle import Toggle
from starpulse._internal.board.seam import Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.eventlog.event_log import Entry, EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pull_events import RecordProjection
from starpulse._internal.pulls.pulls import PullStore
from starpulse.contracts.adapters import BoardTask
from starpulse.tests.leak_gate import BUDGETS, check, measures_allocations
from starpulse.tests.machines import MACHINES

pytestmark = measures_allocations

REPO = "acme/widgets"
PROFILE = "@agent-standard-high"
TASK_IDS = ("T-1", "T-2", "T-3")
MINUTE = 60.0


def _pull_events_step() -> Callable[[], None]:
    """An event pass whose checks flip every time, so each one patches and saves the task's pull request record."""
    store = PullStore(create_engine("sqlite://"))
    feed = BoardFeed()
    feed.put(task("PROJ-1", "In Progress", references=[f"https://github.com/{REPO}/pull/1"]))
    projection = RecordProjection(store, feed, lambda: None)
    events = cycle(("CHECKS_PASSED", "CHECKS_FAILED"))
    clock = cycle(float(second) for second in range(1_000, 1_000_000, 60))

    def step() -> None:
        at = next(clock)
        fields = {"machine": "github-pull-request", "event": next(events), "task": "PROJ-1", "time": str(at)}
        projection.handle(Entry(1, "machine:events", f"{at}", fields, at))

    return step


def _autopilot_step(tmp_path: Path) -> tuple[Callable[[], None], list[int]]:
    """A tick that starts a ready task, then finishes it, over a fixed set of task ids; and the count of starts."""
    now = [10_000.0]
    starts = [0]
    limits = Autopilot().limits
    policy = Autopilot(lane="ready", limits=limits)
    feed = BoardFeed(machines={**MACHINES, **HARNESS_MACHINES})
    sampler = Sampler(
        policy.limits,
        probe=lambda: {"cpu": 5.0, "memory": 5.0},
        sessions=lambda: 0,
        review=lambda: 0,
        on_crossing=lambda crossing: None,
        clock=lambda: now[0],
    )
    log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")

    def start(task_id: str, *, harness: str = "claude") -> str:
        starts[0] += 1
        return f"https://claude.ai/code/{task_id}"

    toggle = Toggle(log, tmp_path / "toggle.json")
    toggle.set(True)
    loop = Loop(
        feed=feed,
        policy=policy,
        toggle=toggle,
        sampler=sampler,
        ledger=Ledger(log, tmp_path / "runs.jsonl"),
        start=start,
        settle=lambda task_id, reason: Written(True, task_id),
        chain=lambda: {},
        lane="ready",
        claim=lambda task_id, text: Written(True, task_id),
        clock=lambda: now[0],
        quiet_hours=lambda: None,
        log=log,
    )
    ids = cycle(TASK_IDS)

    def put(task_id: str, lane: str) -> None:
        feed.put(
            BoardTask(
                id=task_id, team="demo", title=task_id, lane=lane, labels=["size-8"], profile=PROFILE, dependencies=()
            )
        )

    def step() -> None:
        task_id = next(ids)
        put(task_id, "ready")
        now[0] += 60 * MINUTE
        loop.tick()
        put(task_id, "done")

    return step, starts


def test_pull_events_stay_within_their_retained_memory_budget() -> None:
    check("pull-events", _pull_events_step(), BUDGETS["pull-events"])


def test_autopilot_stays_within_its_retained_memory_budget(tmp_path: Path) -> None:
    step, starts = _autopilot_step(tmp_path)

    retained = check("autopilot", step, BUDGETS["autopilot"])

    assert starts[0] > 0, f"the loop started nothing, so {retained} B measures an idle loop"
