"""A breaking change posted to the ingest is one log row per commit and one detection per detector."""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.event_log import breaking_change_events as events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound import history
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runs.adapters.inbound.cloudevents import SINGLE, CloudEventsIngest
from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
from starpulse.runs.model.config import Producer

from tests.machines import MACHINES

PRODUCER = Producer("trantor", "TRANTOR_TOKEN", machines=(), actors=())
COMMIT = "aee9abcd06"


def _post(ingest: CloudEventsIngest, id: str, type: str, subject: str | None, data: dict) -> int:
    body = {
        "specversion": "1.0",
        "id": id,
        "source": "trantor",
        "type": type,
        "time": "2026-11-03T14:00:00+00:00",
        "data": data,
        **({"subject": subject} if subject is not None else {}),
    }
    return ingest("Bearer s", SINGLE, json.dumps(body).encode())[0]


def _recorded(ingest: CloudEventsIngest, id: str, detector: str, commit: str | None = COMMIT) -> int:
    data = {"detector": detector, "outcome": "revert-opened", "pr": 7738, "task": "TASK-10815"}
    return _post(ingest, id, events.RECORDED, commit, data)


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not done():
        assert time.monotonic() < deadline, "the breaking change never arrived"
        time.sleep(0.01)


@pytest.fixture
def stop():
    event = StopEvent()
    yield event
    event.set()


def test_two_detectors_on_one_commit_leave_one_row_with_two_detections_until_it_is_postmortemed(
    tmp_path: Path, stop: threading.Event
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    ingest = CloudEventsIngest({"trantor": PRODUCER}, ingest_tokens([PRODUCER], {"TRANTOR_TOKEN": "s"}), log, {})
    threading.Thread(target=history.record_breaking_changes, args=(store, log, stop), daemon=True).start()

    assert _recorded(ingest, "e1", "post-merge-revert") == 201
    assert _recorded(ingest, "e2", "red-main") == 201
    assert _recorded(ingest, "e2", "red-main") == 201  # a replayed event id changes nothing
    _until(lambda: any(len(row["detections"]) == 2 for row in store.breaking_changes()))

    (row,) = store.breaking_changes(open_only=True)
    assert (row["commit"], row["pr"], row["task"], row["outcome"], row["postmortem_task"]) == (
        COMMIT,
        7738,
        "TASK-10815",
        "revert-opened",
        None,
    )
    assert sorted(d["detector"] for d in row["detections"]) == ["post-merge-revert", "red-main"]

    assert _post(ingest, "p1", events.POSTMORTEMED, COMMIT, {"task": "TASK-12000"}) == 201
    _until(lambda: store.breaking_changes(open_only=True) == [])

    (closed,) = store.breaking_changes()
    assert closed["postmortem_task"] == "TASK-12000"
    assert len(closed["detections"]) == 2


@pytest.mark.parametrize(
    ("type", "subject", "data"),
    [
        (events.RECORDED, None, {"detector": "red-main", "outcome": "reverted"}),
        (events.RECORDED, COMMIT, {"outcome": "reverted"}),
        (events.POSTMORTEMED, None, {"task": "TASK-1"}),
    ],
)
def test_ingest_refuses_an_event_with_no_commit_or_no_detector(
    tmp_path: Path, type: str, subject: str | None, data: dict
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    ingest = CloudEventsIngest({"trantor": PRODUCER}, ingest_tokens([PRODUCER], {"TRANTOR_TOKEN": "s"}), log, {})

    assert _post(ingest, "bad", type, subject, data) == 400
