"""A stream reads the snapshot the background thread built: it waits for a stale one and never builds it itself."""

import threading
import urllib.request
from pathlib import Path

import pytest

from starpulse.board.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import next_event as _next_event
from starpulse._internal.kit.adapter_kit import serve as _serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse._internal.server.column_stream import ColumnViews
from starpulse._internal.server.snapshot_cache import SnapshotCache
from starpulse.tests.machines import MACHINES, ROLES


def test_a_stream_never_builds_the_snapshot_on_its_own_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.streams._HELD_SETTLE_S", 0)
    builders: list[str] = []
    build = SnapshotCache._build

    def recording(self: SnapshotCache, max_age_s: float | None = None):
        builders.append(threading.current_thread().name)
        return build(self, max_age_s)

    monkeypatch.setattr(SnapshotCache, "_build", recording)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", assignee="session-1"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?assignee=session-1"), timeout=5) as resp:
            _next_event(resp)
            feed.put(task("PROJ-2", "In Progress", assignee="session-1"))
            _, document = _next_event(resp)

    assert {t["id"] for c in document["columns"] for t in c["tasks"]} == {"PROJ-1", "PROJ-2"}
    assert builders and set(builders) == {"snapshot-cache"}


def test_a_stale_cache_is_waited_on_not_built_by_the_caller() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    cache = SnapshotCache(feed, ttl_s=60, settle_s=0)
    first = cache.get()
    feed.put(task("PROJ-1", "In Progress"))

    served = cache.after_current()

    assert served is not first and served.rev == feed.rev


def test_streams_with_the_same_view_share_one_encoded_frame() -> None:
    views = ColumnViews()
    view = {"columns": [{"state": "Ready", "tasks": []}]}

    assert views.frame(view, "s", ("ready",)) is views.frame(dict(view), "s", ("ready",))
