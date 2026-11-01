"""A held or lanes stream takes the snapshot on the column views' one thread, shared by the streams one change woke."""

import threading
import urllib.request
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import next_event as _next_event
from starpulse.runtime.adapter_kit import serve as _serve
from starpulse.runtime.adapter_kit import task
from starpulse.runtime.adapter_kit import url as _url
from starpulse.views.adapters.inbound.column_stream import ColumnViews
from starpulse.views.adapters.inbound.snapshots import Snapshots

from tests.machines import MACHINES, ROLES


def test_a_stream_takes_the_snapshot_on_the_column_views_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.views.adapters.inbound.api.streams._HELD_SETTLE_S", 0)
    takers: list[str] = []
    take = Snapshots.take

    def recording(self: Snapshots):
        takers.append(threading.current_thread().name)
        return take(self)

    monkeypatch.setattr(Snapshots, "take", recording)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", assignee="session-1"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?assignee=session-1"), timeout=5) as resp:
            _next_event(resp)
            feed.put(task("PROJ-2", "In Progress", assignee="session-1"))
            _, document = _next_event(resp)

    assert {t["id"] for c in document["columns"] for t in c["tasks"]} == {"PROJ-1", "PROJ-2"}
    assert takers and all(name.startswith("column-views") for name in takers)


def test_streams_woken_by_one_change_share_one_snapshot_and_a_change_takes_a_new_one() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    snapshots, views = Snapshots(feed), ColumnViews()
    first = views.take(snapshots)

    shared = views.take(snapshots)
    feed.put(task("PROJ-1", "In Progress"))
    after = views.take(snapshots)

    assert shared is first
    assert after is not first and after.rev == feed.rev


def test_streams_with_the_same_view_share_one_encoded_frame() -> None:
    views = ColumnViews()
    view = {"columns": [{"state": "Ready", "tasks": []}]}

    assert views.frame(view, "s", ("ready",)) is views.frame(dict(view), "s", ("ready",))
