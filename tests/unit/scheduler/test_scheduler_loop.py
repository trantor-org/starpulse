"""The scheduler loop: what a tick starts, finishes and settles, and which feed events wake it."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError
from starpulse.board.board_feed import BoardFeed
from starpulse.board.machine_tasks import MachineTasks
from starpulse.board.model import rules
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import BoardTask, MachineEvent, StartFailedError
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.model.harness import SESSION_MACHINES
from starpulse.scheduler.adapters.loop import IDLE_RETURNED, SETTLE_REFUSED, Loop
from starpulse.scheduler.model.config import Scheduler
from starpulse.scheduler.model.harness_setting import HarnessSetting
from starpulse.scheduler.model.ledger import Ledger
from starpulse.scheduler.model.quiet_hours import QuietHours
from starpulse.scheduler.model.sampler import Sampler
from starpulse.scheduler.model.toggle import Toggle

from tests.machines import MACHINES, ROLES

START = 10_000.0
PROFILE = "@agent-standard-high"  # tier standard: weight 2, so a size-8 task prices 16 percent of CPU and memory


class Rig:
    """A loop over a real feed, sampler and ledger, with a starter and a settle writer that record their calls.

    The test sets the clock, the host's CPU and the tasks; `settle` moves the task to `needs_attention` in the feed, as
    the board writer's change would reach it.
    """

    def __init__(
        self,
        tmp_path: Path,
        limits: Mapping[str, float] | None = None,
        quiet: QuietHours | None = None,
        requeue: bool = False,
        **policy: Any,
    ) -> None:
        self.now = START
        self.host = {"cpu": 5.0, "memory": 5.0}
        self.feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
        self.harness = MachineTasks(self.feed)
        self.policy = Scheduler(lane="ready", limits={**Scheduler().limits, **(limits or {})}, **policy)
        self.sampler = Sampler(
            self.policy.limits,
            probe=lambda: self.host,
            sessions=lambda: 0,
            review=lambda: 0,
            on_crossing=lambda crossing: None,
            clock=lambda: self.now,
        )
        self.log = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")
        self.ledger = Ledger(self.log)
        self.toggle = Toggle(self.log)
        self.toggle.set(True)
        self.harness_setting = HarnessSetting(self.log)
        self.started: list[str] = []
        self.started_harness: list[str] = []
        self.settled: list[tuple[str, str]] = []
        self.refuse_settle = False
        self.requeueing = requeue
        self.requeued: list[tuple[str, str]] = []
        self.failing: set[str] = set()
        self.limit: str | None = None
        self.claims: list[tuple[str, str]] = []
        self.claim_ok = True
        self.merged: set[str] = set()
        self.transcripts: dict[str, float] = {}
        self.quiet = quiet
        self.loop = self._bind(self.sampler)

    def restarted(self) -> Loop:
        """A new loop and sampler over this store: a StarPulse restart."""
        sampler = Sampler(
            self.policy.limits,
            probe=lambda: self.host,
            sessions=lambda: 0,
            review=lambda: 0,
            on_crossing=lambda crossing: None,
            clock=lambda: self.now,
        )
        return self._bind(sampler)

    def _bind(self, sampler: Sampler) -> Loop:
        return Loop(
            feed=self.feed,
            policy=self.policy,
            toggle=self.toggle,
            sampler=sampler,
            ledger=self.ledger,
            start=self._start,
            settle=self._settle,
            chain=lambda: {},
            lane="ready",
            claim=self._claim,
            requeue=self._requeue if self.requeueing else None,
            merged=lambda agent: agent["id"] in self.merged,
            clock=lambda: self.now,
            quiet_hours=lambda: self.quiet,
            log=self.log,
            harness=self.harness_setting,
            transcript=self.transcripts.get,
        )

    def _claim(self, task: str, text: str) -> Written:
        self.claims.append((task, text))
        return Written(self.claim_ok, task)

    def _requeue(self, task: str, comment: str) -> Written:
        self.requeued.append((task, comment))
        self.put(task, "ready")
        return Written(True, task)

    def _start(self, task: str, *, harness: str = "claude", mode: str = "interactive") -> str:
        _ = mode
        if self.limit is not None:
            raise StartFailedError(self.limit)
        if task in self.failing:
            raise StartFailedError(f"no session for {task}")
        self.started.append(task)
        self.started_harness.append(harness)
        return f"https://claude.ai/code/{task}"

    def _settle(self, task: str, reason: str) -> Written:
        self.settled.append((task, reason))
        if self.refuse_settle:
            return Written(
                False, f"{task}: Needs attention needs a non-empty ## Needs attention reason in the description"
            )
        self.put(task, "needs_attention")
        return Written(True, task)

    def put(
        self,
        task: str,
        lane: str = "ready",
        size: int = 8,
        deps: tuple[str, ...] = (),
        impact: str = "",
        urgency: str = "",
        labels: tuple[str, ...] = (),
        assignee: str = "",
    ) -> None:
        self.feed.put(
            BoardTask(
                id=task,
                team="demo",
                title=task,
                lane=lane,
                labels=[f"size-{size}", *labels],
                profile=PROFILE,
                assignee=assignee,
                dependencies=deps,
                impact=impact,
                urgency=urgency,
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


def test_a_restarted_loop_does_not_start_a_ready_task_it_already_started(rig: Rig) -> None:
    rig.put("T-1")
    assert rig.loop.tick() == ["T-1"]

    restarted = rig.restarted()

    assert restarted.tick() == []
    assert rig.started == ["T-1"]


def test_a_restarted_loop_keeps_an_in_progress_run_and_does_not_start_it_again(rig: Rig) -> None:
    rig.put("T-1")
    assert rig.loop.tick() == ["T-1"]
    rig.put("T-1", lane="in_progress")

    restarted = rig.restarted()

    assert restarted.tick() == []
    assert [session["task"] for session in restarted.in_flight()] == ["T-1"]
    assert rig.started == ["T-1"]


def test_a_start_cooldown_blocks_re_admission_when_inflight_state_was_lost(rig: Rig) -> None:
    rig.put("T-1")
    assert rig.loop.tick() == ["T-1"]
    rig.log.delete_setting("scheduler.inflight")

    restarted = rig.restarted()

    assert restarted.tick() == []
    assert rig.started == ["T-1"]


def test_a_tick_starts_a_ready_task_once_and_leaves_it_alone_until_it_finishes(rig: Rig) -> None:
    rig.put("T-1")

    assert rig.loop.tick() == ["T-1"]
    assert rig.loop.tick() == []  # the board still shows it Ready until the session claims it

    assert rig.started == ["T-1"]


def test_a_tick_reads_the_board_once_however_many_runs_are_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = Rig(tmp_path, limits={"cpu": 100, "memory": 100, "sessions": 10})
    for number in range(5):
        rig.put(f"T-{number}", size=1)
    assert len(rig.loop.tick()) == 5
    looked_up: list[str] = []
    lookup = rig.feed.task
    monkeypatch.setattr(rig.feed, "task", lambda task: looked_up.append(task) or lookup(task))

    rig.loop.tick()
    rig.loop.in_flight()

    assert looked_up == []  # each lookup is a read-model query: a tick works from the one list of open tasks


def test_a_ready_task_whose_own_pull_request_merged_is_not_started(rig: Rig) -> None:
    rig.put("T-1")
    rig.put("T-2")
    rig.merged.add("T-1")

    assert rig.loop.tick() == ["T-2"]
    assert rig.started == ["T-2"]
    assert (rig.loop.next_pick() or {}).get("task") != "T-1"


def test_nothing_is_started_while_the_scheduler_is_off(rig: Rig) -> None:
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


def test_a_run_the_store_cannot_record_is_logged_and_the_loop_carries_on(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def refuse(run: object) -> None:
        raise OperationalError("INSERT", {}, Exception("database is locked"))

    monkeypatch.setattr(rig.ledger, "record", refuse)
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.put("T-1", lane="review")

    rig.loop.tick()

    assert "cannot record the run of T-1" in caplog.text


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


#: The guards trantor declares on a move to Needs attention: a reason that names another task, and one with no question.
ATTENTION_GUARDS = rules.load(
    [
        {
            "on": {"to": "needs_attention"},
            "require": {
                "section": {"heading": "Needs attention", "not_matching": r"\bTASK-\d+\b", "except_self": True}
            },
            "reason": "names another task",
        },
        {
            "on": {"to": "needs_attention"},
            "require": {"section": {"heading": "Needs attention", "not_matching": r"\?"}},
            "reason": "states no operator question",
        },
    ]
)


def test_the_settle_reason_passes_the_guards_on_a_move_to_needs_attention(tmp_path: Path) -> None:
    rig = Rig(tmp_path, requeue=True)
    rig.put("TASK-1")
    rig.loop.tick()
    rig.put("TASK-1", lane="in_progress")
    rig.session("TASK-1")
    rig.after(31)
    rig.loop.tick()  # returned to Ready on its first idle settle
    rig.put("TASK-1", lane="in_progress")
    rig.session("TASK-1")
    rig.after(31)

    rig.loop.tick()  # its second idle settle moves it to Needs attention

    [(task, reason)] = rig.settled
    front = {"id": task, "status": "in_progress"}
    refused = rules.standing_refusal(ATTENTION_GUARDS, front, f"## Needs attention\n{reason}\n", "needs_attention")
    assert refused is None, refused.reason


def test_an_idle_task_with_no_pull_request_is_returned_to_ready_with_a_comment(tmp_path: Path) -> None:
    rig = Rig(tmp_path, requeue=True)
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.after(31)

    rig.loop.tick()

    [(task, comment)] = rig.requeued
    assert task == "T-1" and "31 minutes" in comment
    assert "Needs attention" not in comment and "?" not in comment
    assert rig.settled == []
    assert [run.outcome for run in rig.ledger.runs("T-1")] == [IDLE_RETURNED]


def test_a_second_idle_settle_of_the_same_task_settles_it_with_a_reason_that_asks_no_question(tmp_path: Path) -> None:
    rig = Rig(tmp_path, requeue=True)
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.after(31)
    rig.loop.tick()  # returned to Ready, then admitted again in the same pass
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.after(31)

    rig.loop.tick()

    [(task, reason)] = rig.settled
    assert task == "T-1" and "?" not in reason
    assert rig.started == ["T-1", "T-1"]
    assert [run.outcome for run in rig.ledger.runs("T-1")] == [IDLE_RETURNED, "needs_attention"]


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
        ("move", {"machine": "harness", "id": "T-1", "agent": {"state": "stopped"}}, True),  # a session stop
        (
            "move",
            {"machine": "harness", "id": "T-1", "agent": {"state": "active"}},
            False,
        ),  # every tool use is one of these
        ("move", {"machine": "in-progress", "id": "T-1", "agent": {"state": "stopped"}}, False),
        ("claim", {"task": "T-1"}, False),
        ("wake", {}, True),  # the toggle turning on, or a sampler crossing
        (
            "scheduler",
            {"sampledAt": 1.0, "enabled": True, "next": {"verdict": "starting"}},
            True,
        ),  # a sample leaves room
        ("scheduler", {"sampledAt": 1.0, "enabled": True, "next": {"verdict": "waits"}}, False),
        ("scheduler", {"sampledAt": 1.0, "enabled": True, "next": None}, False),
        ("scheduler", {"sampledAt": 1.0, "enabled": False, "next": {"verdict": "starting"}}, False),
    ],
)
def test_only_the_events_that_can_free_or_fill_capacity_wake_the_loop(
    rig: Rig, kind: str, data: Mapping[str, Any], wakes: bool
) -> None:
    assert rig.loop.wants(kind, data) is wakes


def test_a_status_of_a_sample_already_seen_does_not_wake_the_loop_again(rig: Rig) -> None:
    status = {"sampledAt": 1.0, "enabled": True, "next": {"verdict": "starting"}}

    assert rig.loop.wants("scheduler", status)
    assert not rig.loop.wants("scheduler", status)  # a tick's own status push carries the sample it ticked on
    assert rig.loop.wants("scheduler", {**status, "sampledAt": 2.0})


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

    assert rig.loop.next_pick() == {
        "task": "T-2",
        "title": "T-2",
        "verdict": "starting",
        "reason": "goes next",
        "priority": "default",
    }


def test_next_pick_names_the_priority_it_ranked_by(rig: Rig) -> None:
    rig.put("T-1", impact="low", urgency="low")
    rig.put("T-2", impact="high", urgency="high")  # nothing waits on either: its weight outranks T-1's
    rig.sampler.sample()

    assert rig.loop.next_pick() == {
        "task": "T-2",
        "title": "T-2",
        "verdict": "starting",
        "reason": "goes next",
        "priority": "high/high",
    }


def test_next_pick_names_the_top_ranked_task_and_the_dimension_it_waits_on_when_nothing_fits(tmp_path: Path) -> None:
    rig = Rig(tmp_path, limits={"cpu": 10})  # the host sits at 5 and a size-8 task draws 16
    rig.put("T-1")
    rig.put("T-2")
    rig.put("T-3", lane="to_do", deps=("T-2",))
    rig.sampler.sample()

    assert rig.loop.next_pick() == {
        "task": "T-2",
        "title": "T-2",
        "verdict": "waits",
        "reason": "cpu",
        "priority": "default",
    }


def test_next_pick_counts_a_started_run_it_will_not_pick_again(tmp_path: Path) -> None:
    rig = Rig(tmp_path, limits={"cpu": 25})  # one size-8 task fits: T-1 starts and takes what T-2 needs
    rig.put("T-1")
    rig.put("T-2")
    assert rig.loop.tick() == ["T-1"]  # the board still shows it Ready

    assert rig.loop.next_pick() == {
        "task": "T-2",
        "title": "T-2",
        "verdict": "waits",
        "reason": "cpu",
        "priority": "default",
    }


def test_needs_operator_lists_the_eligible_kind_decide_tasks_the_loop_never_starts(rig: Rig) -> None:
    rig.put("T-1", labels=("kind-decide",))
    rig.put("T-2", lane="to_do", labels=("kind-decide",))  # not yet in the eligible lane
    rig.put("T-3")

    assert rig.loop.needs_operator() == [{"task": "T-1", "title": "T-1"}]
    assert rig.loop.tick() == ["T-3"]


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


# The rig's clock starts at 10_000 s, 02:46:40 UTC on 1 January 1970, inside this window; 3_600 s is 01:00, outside it.
QUIET = QuietHours("02:00", "04:00", "UTC")
BEFORE_QUIET = 3_600.0


def test_nothing_is_admitted_inside_quiet_hours_and_a_session_in_flight_is_untouched(tmp_path: Path) -> None:
    rig = Rig(tmp_path, quiet=QUIET)
    rig.now = BEFORE_QUIET
    rig.put("T-1")
    assert rig.loop.tick() == ["T-1"]  # outside the window an eligible task is admitted

    rig.now = START
    rig.session("T-1")
    rig.put("T-2")

    assert rig.loop.tick() == [] and rig.started == ["T-1"]
    assert [session["task"] for session in rig.loop.in_flight()] == ["T-1"]

    rig.now = START + 2 * 3600  # 04:46, past the window's end
    rig.session("T-1")

    assert rig.loop.tick() == ["T-2"]


def test_an_idle_session_is_still_settled_inside_quiet_hours(tmp_path: Path) -> None:
    rig = Rig(tmp_path, quiet=QUIET)
    rig.now = BEFORE_QUIET
    rig.put("T-1")
    rig.loop.tick()

    rig.now = START  # inside the window and past idle_minutes: only admission stops
    rig.loop.tick()

    assert [task for task, _ in rig.settled] == ["T-1"]


def test_next_pick_names_quiet_hours_as_why_the_top_task_waits(tmp_path: Path) -> None:
    rig = Rig(tmp_path, quiet=QUIET)
    rig.put("T-1")
    rig.sampler.sample()

    assert rig.loop.next_pick() == {
        "task": "T-1",
        "title": "T-1",
        "verdict": "waits",
        "reason": "quiet hours",
        "priority": "default",
    }


def test_a_session_stop_with_the_task_still_open_closes_the_run_and_does_not_start_it_again(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, limits={"sessions": 1})
    rig.put("T-1")
    rig.loop.tick()
    rig.session("T-1")
    rig.session("T-1", "SESSION_STOPPED")
    rig.put("T-2")

    started = rig.loop.tick()

    assert started == ["T-2"]
    assert [run.outcome for run in rig.ledger.runs("T-1")] == ["session-ended"]
    assert rig.started == ["T-1", "T-2"]
    assert rig.loop.tick() == []  # T-1 stays Ready and is not admitted again
    assert rig.settled == []


def test_a_ready_task_waiting_on_a_full_slot_starts_on_the_first_tick_after_the_slot_frees(tmp_path: Path) -> None:
    rig = Rig(tmp_path, limits={"sessions": 1})
    rig.put("T-1")
    rig.put("T-2")
    assert rig.loop.tick() == ["T-1"]
    rig.session("T-1")
    assert rig.loop.tick() == []  # the one slot is T-1's; T-2 waits

    rig.session("T-1", "SESSION_STOPPED")

    assert rig.loop.tick() == ["T-2"]  # one tick after the wake that freed the slot, none later


def test_a_stopped_session_that_becomes_active_again_is_not_admitted_as_a_new_run(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.session("T-1")
    rig.session("T-1", "SESSION_STOPPED")
    rig.loop.tick()
    assert rig.loop.in_flight() == []
    rig.session("T-1", "TOOL_USED")  # a mid-turn reply stops, then a tool starts the session again

    assert rig.loop.tick() == []
    assert [session["task"] for session in rig.loop.in_flight()] == ["T-1"]
    assert rig.started == ["T-1"]


def test_a_held_task_stays_out_of_admission_on_a_new_loop_over_the_same_store(tmp_path: Path) -> None:
    rig = Rig(tmp_path, limits={"sessions": 1})
    rig.put("T-1")
    rig.loop.tick()
    rig.session("T-1")
    rig.session("T-1", "SESSION_STOPPED")
    rig.loop.tick()
    again = Loop(
        feed=rig.feed,
        policy=rig.policy,
        toggle=rig.toggle,
        sampler=rig.sampler,
        ledger=rig.ledger,
        start=rig._start,
        settle=rig._settle,
        chain=lambda: {},
        lane="ready",
        clock=lambda: rig.now,
        log=rig.log,
    )
    rig.put("T-2")

    assert again.tick() == ["T-2"]
    assert rig.started == ["T-1", "T-2"]


def test_moving_a_held_task_out_of_ready_lets_admission_take_it_once_it_is_ready_again(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.session("T-1")
    rig.session("T-1", "SESSION_STOPPED")
    rig.loop.tick()
    rig.put("T-1", lane="to_do")  # a person or the sweep moved it
    rig.loop.tick()
    rig.put("T-1")

    assert rig.loop.tick() == ["T-1"]


def test_a_held_ready_task_is_admitted_once_its_start_cooldown_has_passed(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.session("T-1")
    rig.session("T-1", "SESSION_STOPPED")
    rig.loop.tick()
    rig.after(16)  # past START_COOLDOWN; the task sat in Ready the whole time

    assert rig.loop.tick() == ["T-1"]


def test_a_usage_limit_stop_pauses_that_harness_until_its_reset(rig: Rig) -> None:
    rig.limit = "You've hit your weekly limit · resets 9pm (UTC)"
    rig.put("T-1")
    rig.put("T-2")

    assert rig.loop.tick() == []
    assert rig.started == []
    assert rig.loop.pauses() == [
        {"harness": "claude", "until": 75_600.0, "reason": "usage limit"}
    ]  # 21:00 UTC on the clock's day
    assert rig.loop.next_pick() == {
        "task": "T-1",
        "title": "T-1",
        "verdict": "waits",
        "reason": "claude usage limit",
        "priority": "default",
    }

    rig.limit = None
    rig.now = 75_600.0
    assert rig.loop.tick() == ["T-1", "T-2"]
    assert rig.loop.pauses() == []


def test_the_loop_starts_on_the_selected_harness(rig: Rig) -> None:
    rig.harness_setting.set("cursor")
    rig.put("T-1")

    assert rig.loop.tick() == ["T-1"]
    assert rig.started_harness == ["cursor"]


def test_a_credit_pause_on_claude_does_not_block_cursor_admission(rig: Rig) -> None:
    rig.limit = "You've hit your weekly limit · resets 9pm (UTC)"
    rig.put("T-1")
    assert rig.loop.tick() == []
    assert rig.loop.pauses()[0]["harness"] == "claude"

    rig.limit = None
    rig.harness_setting.set("cursor")
    rig.put("T-2")

    assert rig.loop.tick() == ["T-1", "T-2"]
    assert rig.started_harness == ["cursor", "cursor"]
    assert rig.loop.pauses() == [{"harness": "claude", "until": 75_600.0, "reason": "usage limit"}]


def test_each_harness_has_its_own_session_cap(rig: Rig) -> None:
    rig.policy = Scheduler(
        lane="ready",
        limits={**Scheduler().limits, "sessions": 3},
        session_limits={"claude": 1, "cursor": 2},
    )
    rig.loop = rig._bind(rig.sampler)
    rig.put("T-1")
    rig.put("T-2")

    assert rig.loop.tick() == ["T-1"]  # Claude cap is 1
    assert rig.loop.next_pick()["reason"] == "sessions"
    assert rig.loop.sessions_by_harness() == {
        "claude": {"use": 1.0, "limit": 1.0},
        "cursor": {"use": 0.0, "limit": 2.0},
    }

    rig.harness_setting.set("cursor")
    assert rig.loop.tick() == ["T-2"]
    assert rig.started_harness == ["claude", "cursor"]


def test_a_session_started_outside_the_loop_takes_a_session_slot(rig: Rig) -> None:
    rig.policy = Scheduler(lane="ready", limits={**Scheduler().limits, "sessions": 1})
    rig.loop = rig._bind(rig.sampler)
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")  # opened by /api/start, so not one of the loop's runs
    rig.put("T-2")

    assert rig.loop.tick() == []
    assert [session["task"] for session in rig.loop.in_flight()] == ["T-1"]

    rig.session("T-1", "SESSION_STOPPED")
    assert [session["task"] for session in rig.loop.in_flight()] == ["T-1"]  # a mid-turn reply stops it, still live
    rig.after(31)  # past STALE_S with no event: the session is gone
    assert rig.loop.in_flight() == []


def test_in_flight_lists_an_in_progress_task_whose_assignee_session_wrote_a_transcript_within_stale_s(rig: Rig) -> None:
    rig.put("T-1", lane="in_progress", assignee="b55dc5cc")
    rig.session("T-9")  # the harness machine keyed the session by the branch it opened on, not the task it claimed
    rig.transcripts["b55dc5cc"] = rig.now

    assert [session["task"] for session in rig.loop.in_flight()] == ["T-1"]
    assert rig.loop.in_flight()[0]["url"] == ""

    rig.after(31)  # past STALE_S with no transcript write: the session is gone
    assert rig.loop.in_flight() == []


def test_in_flight_ignores_a_transcript_of_a_session_that_holds_no_in_progress_task(rig: Rig) -> None:
    rig.put("T-1", lane="ready", assignee="b55dc5cc")
    rig.put("T-2", lane="in_progress", assignee="other")
    rig.transcripts["b55dc5cc"] = rig.now

    assert rig.loop.in_flight() == []


def test_a_run_its_session_stopped_mid_turn_stays_in_flight_until_the_session_goes_quiet(rig: Rig) -> None:
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.session("T-1", "SESSION_STOPPED")
    rig.loop.tick()  # closes the run and holds the task

    assert "T-1" not in rig.loop._running
    assert [session["task"] for session in rig.loop.in_flight()] == ["T-1"]

    rig.after(31)

    assert rig.loop.in_flight() == []


def test_refused_settle_releases_run_from_inflight_set(rig: Rig) -> None:
    """A run whose settle is refused leaves the in-flight set and frees its session and demand, and is not retried."""
    rig.refuse_settle = True
    rig.put("T-1")
    rig.loop.tick()
    rig.put("T-1", lane="in_progress")
    rig.session("T-1")
    rig.after(31)  # past the 30 minute default

    rig.loop.tick()
    rig.loop.tick()

    assert [task for task, _ in rig.settled] == ["T-1"]  # refused once, not retried each tick
    assert "T-1" not in rig.loop._running
    assert [run.outcome for run in rig.ledger.runs("T-1")] == [SETTLE_REFUSED]
