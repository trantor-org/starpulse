"""The machine:events contract: what one entry carries and where a publish sends it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from starpulse.store import events
from starpulse.store.event_log import EventLog, Tail


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def _publish(log: EventLog, **keys: Any) -> int | None:
    return events.publish("in-progress", "RED_PROVEN", actor="agent", now=5.5, log=log, **keys)


def _appended(log: EventLog) -> list[dict[str, Any]]:
    return [entry.fields for entry in Tail(log, events.STREAM).poll()]


def test_a_task_event_is_appended_with_its_machine_event_task_actor_and_time(log: EventLog) -> None:
    cursor = _publish(log, task="PROJ-7")

    assert cursor == 1
    assert _appended(log) == [
        {"machine": "in-progress", "event": "RED_PROVEN", "task": "PROJ-7", "actor": "agent", "time": 5.5}
    ]


def test_a_run_event_carries_its_run_and_no_task(log: EventLog) -> None:
    _publish(log, run="run-1")

    assert _appended(log) == [
        {"machine": "in-progress", "event": "RED_PROVEN", "run": "run-1", "actor": "agent", "time": 5.5}
    ]


@pytest.mark.parametrize("keys", [{}, {"task": "PROJ-7", "run": "run-1"}])
def test_an_event_keyed_by_neither_or_both_is_refused(log: EventLog, keys: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="in-progress RED_PROVEN: key an event by exactly one of task or run"):
        _publish(log, **keys)

    assert _appended(log) == []


def test_the_time_defaults_to_now(log: EventLog, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events.time, "time", lambda: 42.0)

    events.publish("in-progress", "RED_PROVEN", actor="agent", task="PROJ-7", log=log)

    assert _appended(log)[0]["time"] == 42.0


def test_a_publish_to_a_database_that_cannot_be_opened_returns_none_instead_of_raising(tmp_path: Path) -> None:
    unreachable = EventLog(f"sqlite:///{tmp_path / 'missing-directory' / 'events.sqlite'}")

    assert _publish(unreachable, task="PROJ-7") is None
