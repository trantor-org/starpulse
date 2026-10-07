"""The lane stream's edges: what the hub refuses, what two sources may share, and when the feed appends."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from starpulse import lane_events
from starpulse.board_feed import BoardFeed
from starpulse.contracts import BoardTask
from starpulse.ingest import ForwardIngest
from starpulse.store.event_log import EventLog, Tail
from starpulse.store.history import HistoryStore
from starpulse.tests.machines import MACHINES

GOOD = {"task": "T-1", "lane": "in_progress", "time": 5.0}


def _post(ingest: ForwardIngest, fields: dict) -> dict:
    body = {"opt_in": False, "events": [{"event_id": "T-1@in_progress@5.0", "stream": lane_events.STREAM, "fields": fields}]}
    status, answer = ingest("Bearer tok", json.dumps(body).encode())
    assert status == 200
    return answer


@pytest.mark.parametrize(
    "bad",
    [
        {**GOOD, "lane": ""},
        {key: value for key, value in GOOD.items() if key != "task"},
        {**GOOD, "time": "5"},
        {**GOOD, "time": -1},
        {**GOOD, "labels": "x"},
        {**GOOD, "team": 3},
    ],
)
def test_the_hub_refuses_a_lane_entry_the_contract_does_not_allow(tmp_path: Path, bad: dict) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'hub.sqlite'}")

    assert _post(ForwardIngest({"ana": "tok"}, log), bad) == {"accepted": 0, "rejected": 1}
    assert Tail(log, lane_events.STREAM).poll() == []


def test_the_hub_keeps_a_lane_entry_under_its_source_and_drops_a_field_the_contract_lacks(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'hub.sqlite'}")

    assert _post(ForwardIngest({"ana": "tok"}, log), {**GOOD, "title": "secret", "labels": ["a"]})["accepted"] == 1

    [entry] = Tail(log, lane_events.STREAM).poll()
    assert entry.event_id == "ana/T-1@in_progress@5.0"
    assert entry.fields == {**GOOD, "labels": ["a"], "source": "ana"}


def test_two_sources_that_key_a_task_alike_each_keep_their_own_lane_history(tmp_path: Path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'hub.sqlite'}", MACHINES)

    assert store.record_lane_entry("ana/T-1@in_progress@5.0", GOOD) is True
    assert store.record_lane_entry("bob/T-1@in_progress@6.0", {**GOOD, "time": 6.0}) is True  # not ana's repeat
    assert store.record_lane_entry("ana/T-1@in_progress@7.0", {**GOOD, "time": 7.0}) is False  # ana's own repeat

    assert sorted(event_id for event_id, *_ in store.lane_changes()) == [
        "ana/T-1@in_progress@5.0",
        "bob/T-1@in_progress@6.0",
    ]


def test_a_lane_entry_is_appended_only_when_the_history_wrote_a_row(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'ic.sqlite'}")
    store = HistoryStore(f"sqlite:///{tmp_path / 'ic.sqlite'}", MACHINES)
    clock = iter(range(100, 200))
    feed = BoardFeed(machines=MACHINES, clock=lambda: float(next(clock)))
    feed.record_lanes(store, log)
    store.record_lane("T-1@in_progress@50.0", "T-1", "in_progress", 50.0)  # the history already has this lane

    feed.put(BoardTask(id="T-1", team="demo", title="t", lane="in_progress"))
    feed.put(BoardTask(id="T-2", team="demo", title="t", lane="review", labels=("kind-execute",), milestone="m-1"))

    [entry] = Tail(log, lane_events.STREAM).poll()
    assert entry.event_id.startswith("T-2@review@")
    assert entry.fields["labels"] == ["kind-execute"] and entry.fields["milestone"] == "m-1"
    assert "title" not in entry.fields
