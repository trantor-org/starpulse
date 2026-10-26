"""The event store: compare-and-swap appends, upcast reads, the outbox and retention that spares it."""

import time
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import StatementError
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion, Upcasters


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


@pytest.fixture
def engine(log: EventLog) -> Engine:
    return log.engine


def _event(type: str = "TaskCreated", **payload: object) -> NewEvent:
    return NewEvent(type=type, payload=payload, actor="adin", writer="operator", correlation_id="c-1")


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as db:
        return db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_an_append_at_a_stale_version_is_refused(engine: Engine) -> None:
    store = EventStore(engine)
    store.append("task", "TASK-1", 0, [_event(title="a")])

    with pytest.raises(StaleVersion):
        store.append("task", "TASK-1", 0, [_event(title="b")])

    assert store.head("task", "TASK-1") == 1
    assert [e.payload["title"] for e in store.read("task", "TASK-1")] == ["a"]


def test_an_append_numbers_events_from_the_head_and_keeps_the_envelope(engine: Engine) -> None:
    store = EventStore(engine)
    first = store.append("task", "TASK-1", 0, [_event(title="a")], at=10.0)
    second = store.append("task", "TASK-1", 1, [_event("FieldsEdited", title="b"), _event("Released")], at=11.0)

    assert [e.version for e in first + second] == [1, 2, 3]
    assert len({e.event_id for e in first + second}) == 3
    read = store.read("task", "TASK-1")
    assert read == first + second
    assert (read[0].subject_kind, read[0].subject_id, read[0].actor, read[0].writer) == (
        "task",
        "TASK-1",
        "adin",
        "operator",
    )
    assert read[0].at == 10.0
    assert read[0].correlation_id == "c-1"
    assert store.read("task", "TASK-1", after=2) == [read[2]]


def test_streams_of_two_subjects_do_not_share_versions(engine: Engine) -> None:
    store = EventStore(engine)
    store.append("task", "TASK-1", 0, [_event()])
    store.append("task", "TASK-2", 0, [_event()])
    store.append("run", "TASK-1", 0, [_event("RunStarted")])

    assert [store.head("task", "TASK-1"), store.head("task", "TASK-2"), store.head("run", "TASK-1")] == [1, 1, 1]


def test_a_failed_append_leaves_neither_event_nor_outbox_row(engine: Engine) -> None:
    store = EventStore(engine)

    with pytest.raises(StatementError):
        store.append("task", "TASK-1", 0, [_event(title="ok"), _event(title=object())])

    assert store.head("task", "TASK-1") == 0
    assert (_count(engine, "starpulse_stream_events"), _count(engine, "starpulse_outbox")) == (0, 0)


def test_a_v1_payload_is_read_as_v2_and_the_stored_row_is_unchanged(engine: Engine) -> None:
    EventStore(engine).append("task", "TASK-1", 0, [_event("FieldsEdited", name="x")])
    upcasters = Upcasters()
    upcasters.register("FieldsEdited", 1, lambda payload: {"title": payload["name"]})

    (event,) = EventStore(engine, upcasters).read("task", "TASK-1")

    assert (event.schema_version, event.payload) == (2, {"title": "x"})
    with engine.connect() as db:
        stored = db.execute(text("SELECT schema_version, payload FROM starpulse_stream_events")).one()
    assert stored[0] == 1
    assert '"name"' in stored[1]


def test_an_appended_event_waits_in_the_outbox_until_marked_sent(engine: Engine) -> None:
    store = EventStore(engine)
    written = store.append("task", "TASK-1", 0, [_event(), _event("Released")])

    assert store.outbox_pending() == written
    store.mark_sent([written[0].event_id])
    assert store.outbox_pending() == written[1:]
    store.mark_sent([written[0].event_id, written[1].event_id])
    assert store.outbox_pending() == []
    assert _count(engine, "starpulse_stream_events") == 2


def test_pruning_the_event_log_leaves_the_store_untouched(log: EventLog, engine: Engine, tmp_path: Path) -> None:
    store = EventStore(engine)
    store.append("task", "TASK-1", 0, [_event()], at=1.0)
    log._append("lane", {"x": 1})
    before = _count(engine, "starpulse_stream_events")

    pruned = log.prune(0, now=time.time() + 10, archive_dir=tmp_path / "archive")

    assert pruned == 1
    assert _count(engine, "starpulse_stream_events") == before == 1
    assert store.read("task", "TASK-1")


def test_events_of_a_kind_are_read_after_a_position_in_the_order_every_stream_was_appended(engine: Engine) -> None:
    store = EventStore(engine)
    store.append("task", "TASK-1", 0, [_event(title="a")])
    store.append("run", "r-1", 0, [_event("RunStarted")])
    store.append("task", "TASK-2", 0, [_event(title="b")])
    store.append("task", "TASK-1", 1, [_event("FieldsEdited", changes={})])

    first = store.read_after("task", 0, limit=2)
    rest = store.read_after("task", first[-1].position)

    assert [(e.subject_id, e.version) for e in first] == [("TASK-1", 1), ("TASK-2", 1)]
    assert [(e.subject_id, e.version) for e in rest] == [("TASK-1", 2)]
    assert store.read_after("task", rest[-1].position) == []
    assert first[0].position < first[1].position < rest[0].position
