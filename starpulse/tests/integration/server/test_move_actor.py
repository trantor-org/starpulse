"""An accepted move leaves a `board:lanes` row that names who made it: `agent` through the CLI, `operator` from the page."""

import json
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from starpulse._internal.board import native
from starpulse._internal.cli import agent_cli as cli
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.contracts import LaneEvent
from starpulse.contracts.adapters import Move
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.board.test_native import write_task


@contextmanager
def _served(tmp_path: Path) -> Iterator[tuple[str, BoardFeed, EventLog]]:
    """A server over a native board holding `task-1` and `task-2` In Progress, a feed that logs each lane change."""
    native.board({}, tmp_path)
    for key in ("task-1", "task-2"):
        write_task(tmp_path, key, "In Progress")
    built = native.board({}, tmp_path)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(machines=MACHINES)
    feed.record_lanes(HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES), log)
    for key in ("task-1", "task-2"):
        feed.put(task(key, "In Progress", moves={"done": Move(allowed=True)}))
    with serve(tmp_path, feed, writer=built.writer) as server:
        yield url(server, ""), feed, log


def _page_move(server: str, key: str) -> None:
    """The page's move of `key` to Done, which names the operator."""
    post = urllib.request.Request(
        f"{server}/api/move",
        data=json.dumps({"task": key, "to": "done", "actor": "operator"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(post, timeout=5) as response:
        assert response.status == 200


def _actors(log: EventLog) -> dict[str, str | None]:
    """The actor each task's Done entry names, None where the entry names none."""
    entries = Tail(log, lane_events.STREAM).poll()
    return {e.fields["task"]: e.fields.get("actor") for e in entries if e.fields["lane"] == "done"}


def test_a_page_move_and_a_cli_move_each_leave_a_lane_entry_naming_their_actor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _served(tmp_path) as (server, feed, log):
        _page_move(server, "task-1")
        feed.put(task("task-1", "Done"))  # the board's watcher reads the file the move wrote
        assert cli.main(["task", "move", "task-2", "done", "--server", server], {}) == 0
        capsys.readouterr()
        feed.put(task("task-2", "Done"))

    assert _actors(log) == {"task-1": "operator", "task-2": "agent"}
    for entry in Tail(log, lane_events.STREAM).poll():
        LaneEvent.model_validate(entry.fields)
