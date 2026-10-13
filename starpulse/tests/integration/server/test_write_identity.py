"""A server write names its session and harness: each verb leaves a `board:lanes` row carrying both, a create stamps
`created_by`, and a write that names no session is recorded as `anonymous`, never as the operator."""

import json
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from starpulse._internal.board import native
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.contracts import LaneEvent
from starpulse.contracts.adapters import Move
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.board.test_native import native_root, write_task

WHO = {"session": "9c56ca8b", "harness": "cursor"}


@contextmanager
def _served(tmp_path: Path) -> Iterator[tuple[str, BoardFeed, EventLog]]:
    """A server over a native board holding `task-1` to `task-3` In Progress, a feed that logs each lane change."""
    native.board({}, tmp_path)
    keys = ("task-1", "task-2", "task-3")
    for key in keys:
        write_task(tmp_path, key, "In Progress")
    built = native.board({}, tmp_path)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(machines=MACHINES)
    feed.record_lanes(HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES), log)
    for key in keys:
        feed.put(task(key, "In Progress", moves={"done": Move(allowed=True)}))
    with serve(
        tmp_path,
        feed,
        writer=built.writer,
        read=built.read,
        edit=built.edit,
        archive=built.archive,
        create=built.create,
    ) as server:
        yield url(server, ""), feed, log


def _post(server: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{server}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def _row(log: EventLog, key: str, lane: str) -> dict[str, Any]:
    """The `board:lanes` entry that has `key` enter `lane`."""
    rows = [e.fields for e in Tail(log, lane_events.STREAM).poll() if e.fields["task"] == key]
    return next(fields for fields in rows if fields["lane"] == lane)


def test_each_verb_leaves_a_lane_row_naming_the_session_and_harness_and_a_create_stamps_created_by(
    tmp_path: Path,
) -> None:
    with _served(tmp_path) as (server, feed, log):
        _post(server, "/api/move", {"task": "task-1", "to": "done", "actor": "agent", **WHO})
        feed.put(task("task-1", "Done"))
        base =json.loads(urllib.request.urlopen(f"{server}/api/task/task-2", timeout=5).read())["record"]
        _post(
            server,
            "/api/edit",
            {"task": "task-2", "base": {"status": base["status"]}, "changes": {"status": "Done"}, "actor": "agent", **WHO},
        )
        feed.put(task("task-2", "Done"))
        _post(server, "/api/archive", {"task": "task-3", "reason": "probe", "actor": "agent", **WHO})
        feed.put(task("task-3", "In Progress", settled="archived"))
        made = _post(server, "/api/tasks", {"title": "Probe", "actor": "agent", **WHO})["task"]
        feed.put(task(made, "To Do"))

    for key, lane in (("task-1", "done"), ("task-2", "done"), ("task-3", "archived"), (made, "to_do")):
        row = _row(log, key, lane)
        assert (row["session"], row["harness"]) == ("9c56ca8b", "cursor"), key
        LaneEvent.model_validate(row)
    created = next((native_root(tmp_path) / "tasks").glob(f"{made}*.md")).read_text()
    assert "created_by: cursor:9c56ca8b\n" in created


def test_a_create_naming_no_actor_and_no_session_is_recorded_as_anonymous_not_the_operator(tmp_path: Path) -> None:
    with _served(tmp_path) as (server, feed, log):
        made = _post(server, "/api/tasks", {"title": "Probe"})["task"]
        feed.put(task(made, "To Do"))

    assert _row(log, made, "to_do")["actor"] == "anonymous"
    created = next((native_root(tmp_path) / "tasks").glob(f"{made}*.md")).read_text()
    assert "created_by: anonymous\n" in created
