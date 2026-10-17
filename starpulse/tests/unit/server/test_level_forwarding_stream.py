"""Level and forwarding status publish on the feed so the page need not poll GET /api/level or /api/forwarding."""

from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.hub.forward import Forwarder
from starpulse._internal.server.live_push import wire_forwarding, wire_level
from starpulse.contracts import BoardTask
from starpulse.tests.machines import MACHINES


def _drain(changes: queue.Queue) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    while True:
        try:
            out.append(changes.get_nowait())
        except queue.Empty:
            return out


def test_a_board_lane_change_publishes_a_level_event() -> None:
    feed = BoardFeed(machines=MACHINES)
    published: list[dict] = []

    def publish_level() -> dict | None:
        body = {
            "now": 1.0,
            "window_s": 3600.0,
            "history_s": 3600.0,
            "machine": "board",
            "goal": "g",
            "level": {
                "title": "t",
                "subject": "s",
                "runs": "r",
                "gates": [],
                "terminals": [],
                "orbit": {"suns": "none", "working": []},
                "facets": [],
                "activity": {"measure": "ended", "pace": "day"},
            },
            "wip": {"count": 0, "states": {}},
            "throughput": {"count": 0, "per_day": 0.0},
            "time_in_state": [],
            "aging": {"threshold_s": None, "runs": []},
            "orbit": {"suns": "none", "terminals": {}, "working": {}},
            "arrivals": [],
            "sources": [],
        }
        published.append(body)
        return body

    wire_level(feed, publish_level, delay_s=0)
    feed.expect("0-0")
    _, changes = feed.subscribe()
    _drain(changes)

    feed.put(BoardTask(id="TASK-1", title="t", lane="in_progress", team="demo"))

    kinds = [kind for kind, _ in _drain(changes)]
    assert "level" in kinds
    assert published


def _forwarder() -> MagicMock:
    forwarder = MagicMock(spec=Forwarder)
    forwarder.status.return_value = {
        "url": "http://hub.example/api/forward",
        "optIn": False,
        "names": False,
        "refused": False,
        "lastSent": None,
        "problem": None,
        "next": [],
        "more": False,
        "contract": {},
    }
    forwarder.opt_in = MagicMock()
    return forwarder


def _forwarding(changes: queue.Queue) -> list[dict]:
    return [data for kind, data in _drain(changes) if kind == "forwarding"]


def test_the_returned_push_publishes_a_forwarding_event(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    push = wire_forwarding(feed, _forwarder())
    _, changes = feed.subscribe()
    _drain(changes)

    push()

    events = _forwarding(changes)
    assert events and events[-1]["configured"] is True


def test_an_opt_in_change_forgets_the_status_and_publishes_a_forwarding_event(tmp_path: Path) -> None:
    feed = BoardFeed(machines=MACHINES)
    forwarder = _forwarder()
    original_set = forwarder.opt_in.set
    wire_forwarding(feed, forwarder)
    _, changes = feed.subscribe()
    _drain(changes)

    forwarder.opt_in.set(True)

    original_set.assert_called_once_with(True)
    forwarder.forget_status.assert_called_once_with()
    assert _forwarding(changes)
