"""Serve puts the lanes a restart left unrecorded in the history once the Board has been read."""

from __future__ import annotations

import logging
import threading
from typing import Any

import pytest

from starpulse.api.writes import reconcile_lanes


class _Feed:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.reconciled: list[Any] = []

    def reconcile_lanes(self, current: Any) -> int:
        self.reconciled.append(current)
        return 2


class _Store:
    def __init__(self, down: bool = False) -> None:
        self.down = down

    def current_lanes(self) -> list[tuple[str, str, str, float]]:
        if self.down:
            raise OSError("database is locked")
        return [("T-1@ready@1.0", "T-1", "ready", 1.0)]


def test_the_reconcile_waits_for_the_board_to_be_read_then_hands_the_feed_the_current_lanes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed = _Feed()
    worker = threading.Thread(target=reconcile_lanes, args=(feed, _Store()))
    worker.start()
    worker.join(0.2)
    assert worker.is_alive() and feed.reconciled == []

    with caplog.at_level(logging.WARNING):
        feed.ready.set()
        worker.join(5)

    assert feed.reconciled == [[("T-1@ready@1.0", "T-1", "ready", 1.0)]]
    assert "reconciled the lane of 2 tasks" in caplog.text


def test_a_history_that_is_down_is_logged_and_does_not_end_the_thread_in_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    feed = _Feed()
    feed.ready.set()

    with caplog.at_level(logging.ERROR):
        reconcile_lanes(feed, _Store(down=True))  # type: ignore[arg-type]

    assert feed.reconciled == []
    assert "cannot reconcile the lanes" in caplog.text
