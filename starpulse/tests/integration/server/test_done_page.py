"""GET /api/done: the cold done tasks a page at a time, newest done first, each read from the board on request."""

import json
import urllib.error
import urllib.request
from pathlib import Path

from starpulse._internal.feed.board_feed import HOT_S, BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse.tests.fake_board import bare_board

NOW = 10_000_000.0
RECORDS = {
    f"PROJ-{n}": {"title": f"Title {n}", "profile": "agent", "labels": ["a"], "milestone": "m-1", "type": "story"}
    for n in range(1, 5)
}


def _get(server, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/done{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _feed() -> BoardFeed:
    feed = BoardFeed(clock=lambda: NOW)
    feed.expect("0-0")
    for n, ago in ((1, 3 * HOT_S), (2, 2 * HOT_S), (3, 5 * HOT_S)):  # PROJ-2 is the newest of the cold ones
        feed.put(task(f"PROJ-{n}", "Done", observed_at=NOW - ago))
    feed.put(task("PROJ-4", "Done", observed_at=NOW - 60))  # hot
    return feed


def test_done_page_lists_the_cold_done_tasks_newest_first_a_page_at_a_time(tmp_path: Path) -> None:
    with serve(tmp_path, _feed(), bare_board(read=RECORDS.get)) as server:
        status, first = _get(server, "?limit=2")
        _, second = _get(server, f"?limit=2&before={first['tasks'][-1]['entered']}")

    assert status == 200
    assert [t["id"] for t in first["tasks"]] == ["PROJ-2", "PROJ-1"] and first["more"] is True
    assert [t["id"] for t in second["tasks"]] == ["PROJ-3"] and second["more"] is False
    assert first["tasks"][0] == {
        "id": "PROJ-2",
        "title": "Title 2",
        "state": "done",
        "model": "agent",
        "labels": ["a"],
        "milestone": "m-1",
        "type": "story",
        "entered": NOW - 2 * HOT_S,
    }


def test_done_page_is_404_for_a_board_that_cannot_read_a_task_and_400_for_a_bad_query(tmp_path: Path) -> None:
    with serve(tmp_path, _feed()) as server:
        unreadable = _get(server, "")[0]
    with serve(tmp_path, _feed(), bare_board(read=RECORDS.get)) as server:
        malformed = _get(server, "?limit=0")[0]

    assert (unreadable, malformed) == (404, 400)
