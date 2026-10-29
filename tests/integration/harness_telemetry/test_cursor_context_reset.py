"""A Cursor session over its context limit is asked to wrap up, then restarted on its task, against a real event log."""

from pathlib import Path

import pytest
from starpulse.contracts.adapters import StartFailedError
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.harness_telemetry.adapters.outbound.cursor_context import CONTEXT_STREAM, reset_over_limit

NOW = 1_800_000_000.0
LIMIT, WINDOW, WRAPUP = 150_000, 200_000, "[context-reset] update the working doc, comment, commit WIP"


class FakePanes:
    def __init__(self, panes: dict[str, str]) -> None:
        self.panes, self.sent, self.killed = panes, [], []

    def sessions(self) -> list[str]:
        return list(self.panes)

    def read(self, name: str) -> str:
        return self.panes[name]

    def send(self, name: str, text: str) -> None:
        self.sent.append((name, text))

    def kill(self, name: str) -> None:
        self.killed.append(name)
        del self.panes[name]


def tick(panes: FakePanes, log: EventLog, started: list[str], at: float) -> list[str]:
    def start(task: str, *, harness: str = "claude", mode: str = "interactive") -> str:
        started.append(f"{task}:{harness}:{mode}")
        return "cursor-agent --resume x"

    return reset_over_limit(panes, log, start, limit=LIMIT, window=WINDOW, wrapup=WRAPUP, wrapup_s=600.0, now=at)


def at(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def test_a_session_over_the_limit_is_asked_once_to_wrap_up_and_each_reading_is_recorded(tmp_path: Path) -> None:
    log, started = at(tmp_path), []
    panes = FakePanes({"task-12": "  Auto  80.0%\n", "task-13": "  Auto  20.0%\n"})

    tick(panes, log, started, NOW)

    assert panes.sent == [("task-12", WRAPUP)]
    assert (panes.killed, started) == ([], [])
    rows = {e.fields["task"]: e.fields["tokens"] for e in Tail.replay(log, CONTEXT_STREAM).poll()}
    assert rows == {"TASK-12": 160_000, "TASK-13": 40_000}


def test_a_wrapped_up_session_that_goes_idle_is_killed_and_started_fresh_on_its_task(tmp_path: Path) -> None:
    log, started = at(tmp_path), []
    panes = FakePanes({"task-12": "  Auto  80.0%\n"})

    tick(panes, log, started, NOW)
    panes.panes["task-12"] = "  committing WIP\n  Auto  80.5%\n"
    tick(panes, log, started, NOW + 60)
    assert (panes.killed, started) == ([], [])

    tick(panes, log, started, NOW + 120)

    assert (panes.killed, started) == (["task-12"], ["TASK-12:cursor:interactive"])
    assert panes.sent == [("task-12", WRAPUP)]


def test_a_wrapped_up_session_still_busy_past_the_deadline_is_restarted(tmp_path: Path) -> None:
    log, started = at(tmp_path), []
    panes = FakePanes({"task-12": "  Auto  80.0%\n"})

    tick(panes, log, started, NOW)
    panes.panes["task-12"] = "  working 1\n  Auto  81.0%\n"
    tick(panes, log, started, NOW + 599)
    assert started == []
    panes.panes["task-12"] = "  working 2\n  Auto  82.0%\n"
    tick(panes, log, started, NOW + 601)

    assert (panes.killed, started) == (["task-12"], ["TASK-12:cursor:interactive"])


def test_a_session_that_falls_below_the_limit_is_left_alone_and_asked_afresh_when_it_climbs_again(
    tmp_path: Path,
) -> None:
    log, started = at(tmp_path), []
    panes = FakePanes({"task-12": "  Auto  80.0%\n"})

    tick(panes, log, started, NOW)
    panes.panes["task-12"] = "  Auto  30.0%\n"
    tick(panes, log, started, NOW + 60)
    panes.panes["task-12"] = "  Auto  90.0%\n"
    tick(panes, log, started, NOW + 120)

    assert (panes.killed, started) == ([], [])
    assert panes.sent == [("task-12", WRAPUP), ("task-12", WRAPUP)]


def test_a_stale_wrap_up_request_from_a_gone_session_does_not_restart_a_new_one_unasked(tmp_path: Path) -> None:
    log, started = at(tmp_path), []
    panes = FakePanes({"task-12": "  Auto  80.0%\n"})
    tick(panes, log, started, NOW)

    panes.panes["task-12"] = "  fresh session\n  Auto  85.0%\n"
    tick(panes, log, started, NOW + 10_000)

    assert (panes.killed, started) == ([], [])
    assert panes.sent == [("task-12", WRAPUP), ("task-12", WRAPUP)]


def test_a_failed_restart_is_raised_after_every_other_session_has_been_handled(tmp_path: Path) -> None:
    log = at(tmp_path)
    panes = FakePanes({"task-12": "  Auto  80.0%\n", "task-13": "  Auto  90.0%\n"})
    attempts: list[str] = []

    def start(task: str, *, harness: str = "claude", mode: str = "interactive") -> str:
        attempts.append(task)
        raise StartFailedError("no bridge")

    def run(now: float) -> None:
        reset_over_limit(panes, log, start, limit=LIMIT, window=WINDOW, wrapup=WRAPUP, wrapup_s=600.0, now=now)

    run(NOW)
    panes.panes.update({"task-12": "  wrapping up\n  Auto  80.5%\n", "task-13": "  wrapping up\n  Auto  90.5%\n"})
    run(NOW + 60)
    with pytest.raises(StartFailedError, match="TASK-12.*no bridge"):
        run(NOW + 120)

    assert attempts == ["TASK-12", "TASK-13"]
