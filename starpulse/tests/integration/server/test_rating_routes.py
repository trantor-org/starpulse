"""The rating route: each change to a task's rating is one event, the snapshot reports the latest with its change count,
and a rating the route refuses is no event."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.event_log.event_log import EventLog
from starpulse.tests.fake_board import bare_board
from starpulse.tests.machines import MACHINES, ROLES


@dataclass
class Served:
    url: str

    def post(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(
            f"{self.url}/api/rating", json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def snapshot(self) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.url}/api/snapshot", timeout=5) as response:
            return json.loads(response.read())


@contextmanager
def _served(tmp_path: Path) -> Iterator[Served]:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.record_ratings(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    feed.put(task("task-1", "In Progress"))
    with serve(tmp_path, feed, bare_board()) as server:
        yield Served(url(server, ""))


def test_each_rating_change_is_an_event_and_the_snapshot_reports_the_latest_with_its_count(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        failed = served.post({"task": "task-1", "verdict": "fail", "reason": "Login flakes", "actor": "operator"})
        passed = served.post({"task": "task-1", "verdict": "pass"})
        cleared = served.post({"task": "task-1", "verdict": "cleared", "session": "s-1", "harness": "claude"})

        assert [status for status, _ in (failed, passed, cleared)] == [200, 200, 200]
        assert failed[1] == {"task": "task-1", "verdict": "fail", "reason": "Login flakes", "changes": 1}
        rating = served.snapshot()["ratings"]["task-1"]

        assert (rating["verdict"], rating["reason"], rating["changes"]) == ("cleared", "", 3)


def test_the_snapshot_rating_names_who_made_the_latest_change(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        served.post({"task": "task-1", "verdict": "fail", "actor": "operator"})
        served.post({"task": "task-1", "verdict": "pass", "session": "s-1"})

        assert served.snapshot()["ratings"]["task-1"]["actor"] == "agent"


def test_a_task_never_rated_has_no_rating_in_the_snapshot(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        assert served.snapshot()["ratings"] == {}


def test_a_reason_over_120_characters_or_a_verdict_outside_pass_fail_cleared_is_refused(tmp_path: Path) -> None:
    with _served(tmp_path) as served:
        long_reason = served.post({"task": "task-1", "verdict": "fail", "reason": "x" * 121})
        unknown = served.post({"task": "task-1", "verdict": "miss"})
        at_limit = served.post({"task": "task-1", "verdict": "fail", "reason": "x" * 120})

        assert (long_reason[0], unknown[0]) == (400, 400)
        assert at_limit[0] == 200
        assert served.snapshot()["ratings"]["task-1"]["changes"] == 1
