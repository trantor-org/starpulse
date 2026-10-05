"""The machine:events contract: what one entry carries and where a publish sends it."""

from __future__ import annotations

from typing import Any, cast

import pytest

from starpulse import events
from starpulse.streams import StreamProducer


class FakeProducer:
    def __init__(self) -> None:
        self.emitted: list[dict[str, Any]] = []

    def emit(self, fields: dict[str, Any]) -> str:
        self.emitted.append(fields)
        return "1-0"


def _publish(producer: FakeProducer, **keys: Any) -> str | None:
    return events.publish(
        "in-progress", "RED_PROVEN", actor="agent", now=5.5, producer=cast("StreamProducer", producer), **keys
    )


def test_a_task_event_carries_its_machine_event_task_actor_and_time() -> None:
    producer = FakeProducer()

    assert _publish(producer, task="PROJ-7") == "1-0"
    assert producer.emitted == [
        {"machine": "in-progress", "event": "RED_PROVEN", "task": "PROJ-7", "actor": "agent", "time": 5.5}
    ]


def test_a_run_event_carries_its_run_and_no_task() -> None:
    producer = FakeProducer()

    _publish(producer, run="run-1")

    assert producer.emitted == [
        {"machine": "in-progress", "event": "RED_PROVEN", "run": "run-1", "actor": "agent", "time": 5.5}
    ]


@pytest.mark.parametrize("keys", [{}, {"task": "PROJ-7", "run": "run-1"}])
def test_an_event_keyed_by_neither_or_both_is_refused(keys: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="in-progress RED_PROVEN: key an event by exactly one of task or run"):
        _publish(FakeProducer(), **keys)


def test_the_time_defaults_to_now(monkeypatch: pytest.MonkeyPatch) -> None:
    producer = FakeProducer()
    monkeypatch.setattr(events.time, "time", lambda: 42.0)

    events.publish("in-progress", "RED_PROVEN", actor="agent", task="PROJ-7", producer=cast("StreamProducer", producer))

    assert producer.emitted[0]["time"] == 42.0


def test_a_publish_defaults_to_the_machine_events_stream_on_its_own_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[tuple[str, dict[str, Any]]] = []
    producer = FakeProducer()

    def from_env(prefix: str, **kwargs: Any) -> FakeProducer:
        built.append((prefix, kwargs))
        return producer

    monkeypatch.setattr(StreamProducer, "from_env", from_env)

    events.publish("in-progress", "RED_PROVEN", actor="agent", task="PROJ-7")

    assert built == [("MACHINE_EVENTS", {"stream": "machine:events"})]
    assert len(producer.emitted) == 1
