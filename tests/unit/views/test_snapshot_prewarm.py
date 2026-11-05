"""A page app that keeps its snapshot warm has built the first one before it is returned (TASK-11192), so the server
that serves it never answers a request with a cold build and a restart's queued connections are answered warm."""

from __future__ import annotations

from pathlib import Path

import pytest
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.model.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.asgi_app import page_app
from starpulse.views.adapters.inbound.snapshots import Snapshots

from tests.fake_board import bare_board


def _page_app(tmp_path: Path, refresh_s: float) -> None:
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    page_app(
        feed,
        tmp_path,
        HistoryStore("sqlite://", feed.machines),
        HistoryWindow(feed, 6, log),
        bare_board(),
        snapshot_refresh_s=refresh_s,
    )


@pytest.fixture
def takes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    taken: list[int] = []
    take = Snapshots.take

    def counting(self: Snapshots):
        taken.append(1)
        return take(self)

    monkeypatch.setattr(Snapshots, "take", counting)
    return taken


def test_a_warm_page_app_has_taken_its_first_snapshot_when_it_is_returned(tmp_path: Path, takes: list[int]) -> None:
    _page_app(tmp_path, refresh_s=30.0)

    assert takes == [1]


def test_a_page_app_without_a_refresh_takes_no_snapshot_until_one_is_asked_for(tmp_path: Path, takes: list[int]) -> None:
    _page_app(tmp_path, refresh_s=0.0)

    assert takes == []
