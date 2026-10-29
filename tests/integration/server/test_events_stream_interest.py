"""The main /api/events stream does not rebuild board_columns when a Board task moves."""

import urllib.request
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.view import board_columns
from starpulse.runtime.adapter_kit import next_event as _next_event
from starpulse.runtime.adapter_kit import serve as _serve
from starpulse.runtime.adapter_kit import task
from starpulse.runtime.adapter_kit import url as _url

from tests.machines import MACHINES, ROLES


def test_a_task_move_on_the_main_stream_does_not_call_board_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def counted(*args: object, **kwargs: object) -> dict:
        calls.append(1)
        return board_columns(*args, **kwargs)

    monkeypatch.setattr("starpulse.views.adapters.inbound.column_stream.board_columns", counted)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    feed.put(task("PROJ-2", "To Do"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/events"), timeout=5) as resp:
            assert _next_event(resp)[0] == "snapshot"
            calls.clear()
            feed.put(task("PROJ-1", "In Progress"))
            kind, body = _next_event(resp)

    assert kind == "task"
    assert body["id"] == "PROJ-1"
    assert calls == []
