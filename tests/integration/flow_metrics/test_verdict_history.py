"""A verdict posted to the ingest is kept by the history store and sent on `/api/events`."""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed, follow
from starpulse.board.verdicts import Verdicts
from starpulse.event_log import verdict_events
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore, record_verdicts
from starpulse.runs.adapters.inbound.cloudevents import SINGLE, CloudEventsIngest
from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
from starpulse.runs.model.config import Producer
from starpulse.views.model.encoding import event

from tests.machines import MACHINES

PRODUCER = Producer("qa", "QA_TOKEN", machines=(), actors=())


def _post(ingest: CloudEventsIngest, id: str, lens: str, round: int, outcome: str, reason: str) -> None:
    body = {
        "specversion": "1.0",
        "id": id,
        "source": "qa",
        "type": verdict_events.EVENT,
        "subject": "TASK-1",
        "time": "2026-10-22T12:00:00+00:00",
        "data": {"lens": lens, "round": round, "outcome": outcome, "reason": reason},
    }
    assert ingest("Bearer s", SINGLE, json.dumps(body).encode())[0] == 201


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not done():
        assert time.monotonic() < deadline, "the verdict never arrived"
        time.sleep(0.01)


@pytest.fixture
def stop():
    event = threading.Event()
    yield event
    event.set()


def test_a_posted_verdict_round_trips_through_the_history_store_and_api_events(
    tmp_path: Path, stop: threading.Event
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    feed = BoardFeed(None, machines=MACHINES)
    verdicts = Verdicts(feed)
    ingest = CloudEventsIngest({"qa": PRODUCER}, ingest_tokens([PRODUCER], {"QA_TOKEN": "s"}), log, {})
    _post(ingest, "old", "code", 1, "CHANGES", "replayed")  # before the page connects
    follow(verdicts, log, verdict_events.STREAM, verdicts.handle_entry, stop=stop, interval=0.01)
    _until(verdicts.ready.is_set)
    _, changes = feed.subscribe()
    threading.Thread(target=record_verdicts, args=(store, log, stop), kwargs={"interval": 0.01}, daemon=True).start()

    _post(ingest, "new", "security", 2, "PASS", "no findings")
    kind, data = changes.get(timeout=5)

    assert kind == "verdict"
    assert json.loads(event(kind, data)) == {
        "task": "TASK-1",
        "lens": "security",
        "round": 2,
        "outcome": "PASS",
        "reason": "no findings",
        "at": 1792670400.0,
    }
    _until(lambda: len(store.verdicts("TASK-1")) == 2)
    assert store.verdicts("TASK-1") == [
        {"lens": "code", "round": 1, "outcome": "CHANGES", "reason": "replayed", "at": 1792670400.0},
        {"lens": "security", "round": 2, "outcome": "PASS", "reason": "no findings", "at": 1792670400.0},
    ]
    assert store.verdicts("TASK-2") == []
