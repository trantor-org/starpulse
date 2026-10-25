"""A lane change and its `board:lanes` event commit in one transaction of the one store: both land or neither does."""

from __future__ import annotations

from pathlib import Path

from starpulse.event_log import lane_events
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.flow_metrics.history import HistoryStore
from starpulse.tests.machines import MACHINES

ID = "T-1@ready@100.0"
FIELDS = {"task": "T-1", "lane": "ready", "time": 100.0, "actor": "agent"}


def _store(tmp_path: Path) -> tuple[HistoryStore, EventLog]:
    url = f"sqlite:///{tmp_path / 'store.sqlite'}"
    return HistoryStore(url, MACHINES), EventLog(url)


def test_a_lane_change_and_its_event_land_together(tmp_path: Path) -> None:
    store, log = _store(tmp_path)

    written = store.record_lane(ID, "T-1", "ready", 100.0, event=FIELDS)

    assert (written, store.lane_changes(), [e.fields for e in Tail.replay(log, lane_events.STREAM).poll()]) == (
        True,
        [(ID, "T-1", "ready", 100.0)],
        [FIELDS],
    )


def test_an_event_the_store_refuses_rolls_the_lane_change_back(tmp_path: Path) -> None:
    store, log = _store(tmp_path)

    try:
        store.record_lane(ID, "T-1", "ready", 100.0, event={**FIELDS, "bad": {1, 2}})  # JSON refuses a set
    except Exception:  # noqa: BLE001 - the refusal is the setup; what it left behind is the assertion
        pass

    assert (store.lane_changes(), Tail.replay(log, lane_events.STREAM).poll()) == ([], [])


def test_a_repeated_lane_change_adds_no_event(tmp_path: Path) -> None:
    store, log = _store(tmp_path)
    store.record_lane(ID, "T-1", "ready", 100.0, event=FIELDS)

    written = store.record_lane(ID, "T-1", "ready", 100.0, event=FIELDS)

    assert (written, len(Tail.replay(log, lane_events.STREAM).poll())) == (False, 1)
