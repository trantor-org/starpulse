"""The autopilot loop: what a tick starts, finishes and settles, and which feed events wake it."""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.autopilot.ledger import Ledger
from starpulse._internal.autopilot.loop import Loop
from starpulse._internal.autopilot.sampler import Sampler
from starpulse._internal.autopilot.toggle import Toggle
from starpulse._internal.board.seam import Written
from starpulse._internal.config.autopilot import Autopilot
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.machine_tasks import MachineTasks
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse.contracts.adapters import BoardTask, MachineEvent, StartFailedError
from starpulse.tests.machines import MACHINES

START = 10_000.0
PROFILE = "@agent-standard-high"  # tier standard: weight 2, so a size-8 task prices 16 percent of CPU and memory


class Rig:
    """A loop over a real feed, sampler and ledger, with a starter and a settle writer that record their calls.

    The test sets the clock, the host's CPU and the tasks; `settle` moves the task to `needs_attention` in the feed, as
    the board writer's change would reach it.
    """

    def __init__(self, tmp_path: Path, limits: Mapping[str, float] | None = None, **policy: Any) -> None:
        self.now = START
        self.host = {"cpu": 5.0, "memory": 5.0}
        self.feed = BoardFeed(machines={**MACHINES, **HARNESS_MACHINES})
        self.harness = MachineTasks(self.feed)
        self.policy = Autopilot(lane="ready", limits={**Autopilot().limits, **(limits or {})}, **policy)
        self.sampler = Sampler(
            self.policy.limits,
            probe=lambda: self.host,
            sessions=lambda: 0,
            review=lambda: 0,
            on_crossing=lambda crossing: None,
            clock=lambda: self.now,
        )
        self.ledger = Ledger(tmp_path / "runs.jsonl")
        self.toggle = Toggle(tmp_path / "toggle.json")
        self.toggle.set(True)
        self.started: list[str] = []
        self.settled: list[tuple[str, str]] = []
        self.failing: set[str] = set()
        self.claims: list[tuple[str, str]] = []
        self.claim_ok = True
        self.loop = Loop(
            feed=self.feed,
            policy=self.policy,
            toggle=self.toggle,
            sampler=self.sampler,
            ledger=self.ledger,
            start=self._start,
            settle=self._settle,
            chain=lambda: {},
            lane="ready",
            claim=self._claim,
            clock=lambda: self.now,
        )

    def _claim(self, task: str, text: str) -> Written:
        self.claims.append((task, text))
        return Written(self.claim_ok, task)

    def _start(self, task: str) -> str:
        if task in self.failing:
            raise StartFailedError(f"no session for {task}")
        self.started.append(task)
        return f"https://claude.ai/code/{task}"

    def _settle(self, task: str, reason: str) -> Written:
        self.settled.append((task, reason))
        self.put(task, "needs_attention")
        return Written(True, task)

    def put(self, task: str, lane: str = "ready", size: int = 8, deps: tuple[str, ...] = ()) -> None:
        self.feed.put(
            BoardTask(
                id=task, team="demo", title=task, lane=lane, labels=[f"size-{size}"], assignee=PROFILE, dependencies=deps
            )
        )

    def session(self, task: str, event: str = "SESSION_STARTED") -> None:
        """A harness event for `task` at the rig's clock."""
        self.harness.put(MachineEvent(machine="harness", event=event, task=task, time=self.now))

    def after(self, minutes: float) -> None:
        self.now += minutes * 60


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_a_tick_starts_a_ready_task_once_and_leaves_it_alone_until_it_finishes(rig: Rig) -> None:
    rig.put("T-1")

    assert rig.loop.tick() == ["T-1"]
    assert rig.loop.tick() == []  # the board still shows it Ready until the session claims it

    assert rig.started == ["T-1"]


def test_nothing_is_started_while_the_autopilot_is_off(rig: Rig) -> None:
    rig.toggle.set(False)
    rig.put("T-1")

    assert rig.loop.tick() == []
    assert rig.started == []


def test_a_task_outside_the_eligible_lane_or_with_an_open_dependency_is_not_started(rig: Rig) -> None:
    rig.put("T-1", lane="to_do")
    rig.put("T-2", deps=("T-9",))
    rig.put("T-9", lane="in_progress")

    assert rig.loop.tick() == []


def test_two_tasks_that_do_not_fit_together_are_not_both_started_in_one_pass(tmp_path: Path) -> None:
    # The host sits at 5 percent and each size-8 task draws 16: a limit of 25 holds one, and the second sees the first's.
    rig = Rig(tmp_path, limits={"cpu": 25})
    rig.put("T-1")
    rig.put("T-2")

    started = rig.loop.tick()

    assert started == ["T-1"]
    assert rig.started == ["T-1"]


def test_a_task_that_cannot_start_is_skipped_and_the_next_still_starts(rig: Rig) -> None:
    rig.failing = {"T-1"}
    rig.put("T-1")
    rig.put("T-2")

    started = rig.loop.tick()

    assert started == ["T-2"]
    assert rig.settled == []  # a start that failed settles nothing and requeues nothing


def test_a_runs_capacity_stays_taken_until_its_task_leaves_in_progress(tmp_path: Path) -> None:
    # The host sits at 5 percent and each task draws 16 against a limit of 30: one at a time.
    rig = Rig(tmp_path, limits={"cpu": 30})
    rig.put("T-1")
    rig.put("T-2")
    assert rig.loop.tick() == ["T-1"]
    rig.put("T-1", lane="in_progress")  # its session claimed it and is drawing load
    rig.session("T-1")
    rig.host = {"cpu": 20.0, "memory": 20.0}
    rig.sampler.sample()

    assert rig.loop.tick() == []

    rig.put("T-1", lane="review")  # the task leaves In Progress: the load falls and its capacity frees
    rig.host = {"cpu": 5.0, "memory": 5.0}
    rig.sampler.sample()
    assert rig.loop.tick() == ["T-2"]


def test_a_finished_run_is_recorded_with_its_outcome_duration_and_peak(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.sampler.sample()  # CPU 5 at the start
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.after(10)
    rig.host = {"cpu": 35.0, "memory": 20.0}
    rig.sampler.sample()
    rig.loop.tick()  # sees the load the run is under
    rig.put("T-1", lane="review")
    rig.after(5)

    rig.loop.tick()

    [run] = rig.ledger.runs("T-1")
    assert (run.outcome, run.tier, run.points, run.duration_s) == ("review", "standard", 8, 900.0)
    assert run.peak == {"cpu": 30.0, "memory": 15.0, "sessions": 1, "review": 8}


def test_a_session_idle_past_the_limit_with_its_task_open_is_settled_once_with_a_reason(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.after(31)  # past the 30 minute default

    rig.loop.tick()
    rig.loop.tick()

    [(task, reason)] = rig.settled
    assert task == "T-1"
    assert "31 minutes" in reason and "T-1" in reason
    assert rig.started == ["T-1"]  # never requeued: the settled task is not started again
    assert [run.outcome for run in rig.ledger.runs("T-1")] == ["needs_attention"]


def test_a_session_that_keeps_working_is_not_settled(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    for _ in range(4):
        rig.after(20)
        rig.session("T-1", "TOOL_USED")  # an event every 20 minutes keeps it under the 30 minute limit
        rig.loop.tick()

    assert rig.settled == []


def test_a_session_that_never_claimed_its_task_is_settled_from_when_it_started(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.after(31)

    rig.loop.tick()

    assert [task for task, _ in rig.settled] == ["T-1"]


def test_a_timer_wake_finishes_and_settles_but_starts_nothing(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-2")
    rig.after(31)

    assert rig.loop.tick(admit=False) == []

    assert [task for task, _ in rig.settled] == ["T-1"]
    assert rig.started == ["T-1"]


@pytest.mark.parametrize(
    ("kind", "data", "wakes"),
    [
        ("task", {"id": "T-1", "agent": {"state": "ready"}}, True),  # a task entering the eligible lane
        ("task", {"id": "T-1", "agent": {"state": "to_do"}}, False),
        ("move", {"flow": "harness", "id": "T-1", "agent": {"state": "stopped"}}, True),  # a session stop
        ("move", {"flow": "harness", "id": "T-1", "agent": {"state": "active"}}, False),  # every tool use is one of these
        ("move", {"flow": "in-progress", "id": "T-1", "agent": {"state": "stopped"}}, False),
        ("claim", {"task": "T-1"}, False),
        ("wake", {}, True),  # the toggle turning on, or a sampler crossing
    ],
)
def test_only_the_events_that_can_free_or_fill_capacity_wake_the_loop(
    rig: Rig, kind: str, data: Mapping[str, Any], wakes: bool
) -> None:
    assert rig.loop.wants(kind, data) is wakes


def test_a_running_tasks_own_change_wakes_the_loop(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()

    assert rig.loop.wants("task", {"id": "T-1", "agent": {"state": "review"}})
    assert rig.loop.wants("task", {"id": "T-1", "agent": None})


def test_a_started_task_gets_a_claim_comment_carrying_its_session_address(rig: Rig) -> None:
    rig.put("T-1")

    rig.loop.tick()

    assert [task for task, _ in rig.claims] == ["T-1"]
    assert "https://claude.ai/code/T-1" in rig.claims[0][1]


def test_a_claim_comment_the_board_refuses_leaves_the_session_started(rig: Rig) -> None:
    rig.claim_ok = False
    rig.put("T-1")

    assert rig.loop.tick() == ["T-1"]
    assert rig.started == ["T-1"]


def test_in_flight_lists_each_started_session_with_its_task_model_start_and_address(rig: Rig) -> None:
    assert rig.loop.in_flight() == []  # nothing runs

    rig.put("T-1")
    rig.loop.tick()
    rig.after(2)

    assert rig.loop.in_flight() == [
        {"task": "T-1", "title": "T-1", "model": PROFILE, "started": START, "url": "https://claude.ai/code/T-1"}
    ]


def test_a_run_that_finished_is_no_longer_in_flight(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="review")
    rig.loop.tick()

    assert rig.loop.in_flight() == []


def test_next_pick_is_the_task_admission_would_start_with_its_reason(rig: Rig) -> None:
    rig.put("T-1")
    rig.put("T-2")
    rig.put("T-3", lane="to_do", deps=("T-2",))  # T-2 heads the longer chain, so it ranks first
    rig.sampler.sample()

    assert rig.loop.next_pick() == {"task": "T-2", "title": "T-2", "verdict": "starting", "reason": "goes next"}


def test_next_pick_names_the_top_ranked_task_and_the_dimension_it_waits_on_when_nothing_fits(tmp_path: Path) -> None:
    rig = Rig(tmp_path, limits={"cpu": 10})  # the host sits at 5 and a size-8 task draws 16
    rig.put("T-1")
    rig.put("T-2")
    rig.put("T-3", lane="to_do", deps=("T-2",))
    rig.sampler.sample()

    assert rig.loop.next_pick() == {"task": "T-2", "title": "T-2", "verdict": "waits", "reason": "cpu"}


def test_next_pick_counts_a_started_run_it_will_not_pick_again(tmp_path: Path) -> None:
    rig = Rig(tmp_path, limits={"cpu": 25})  # one size-8 task fits: T-1 starts and takes what T-2 needs
    rig.put("T-1")
    rig.put("T-2")
    assert rig.loop.tick() == ["T-1"]  # the board still shows it Ready

    assert rig.loop.next_pick() == {"task": "T-2", "title": "T-2", "verdict": "waits", "reason": "cpu"}


def test_next_pick_is_none_without_a_reading_or_a_workable_task(rig: Rig) -> None:
    rig.put("T-1")
    assert rig.loop.next_pick() is None  # capacity has not been sampled yet

    rig.sampler.sample()
    rig.put("T-1", lane="to_do")
    assert rig.loop.next_pick() is None


def test_reading_the_next_pick_logs_no_decision(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    rig.put("T-1")
    rig.sampler.sample()

    with caplog.at_level("INFO"):
        rig.loop.next_pick()

    assert caplog.records == []
