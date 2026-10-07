"""GET /api/merges: the merge ledger a page at a time, newest first, back to the 24-hour edge and no further."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse.adapter_kit import serve, url
from starpulse.board_feed import BoardFeed
from starpulse.settings.config import CommitKeys

NOW = datetime(2026, 10, 7, 1, tzinfo=UTC).timestamp()
MACHINE = {
    "states": [
        {"id": "in_progress", "name": "In Progress", "initial": True, "final": False},
        {"id": "done", "name": "Done", "initial": False, "final": True},
    ],
    "transitions": [{"source": "in_progress", "target": "done", "event": "MERGED"}],
}


def _pull(number: int, merged_at: str) -> list[dict]:
    return [
        {
            "url": f"https://github.com/o/trantor/pull/{number}",
            "merged": True,
            "merge_sha": f"{number:040x}",
            "merged_at": merged_at,
        }
    ]


def _get(server: ThreadingHTTPServer, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/merges{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    """Seven merges in the last 24 hours, the 7th and 6th sharing a second, and an eighth beyond the edge."""
    feed = BoardFeed(
        clock=lambda: NOW,
        machines={"board": MACHINE},
        domains={"ci": ["ci/apply"]},
        cues=[{"event": "MERGED", "dag": "ci/apply", "on": "merge", "resolves": "next", "state": "done"}],
        commit={"ci": CommitKeys(after="AFTER")},
    )
    pulls = {f"T-{n}": _pull(n, f"2026-10-07T00:0{n}:00Z") for n in range(1, 7)}
    pulls["T-7"] = _pull(7, "2026-10-07T00:06:00Z")
    pulls["T-8"] = _pull(8, "2026-10-05T00:00:00Z")
    feed.set_pulls(pulls)
    with serve(tmp_path, feed) as server:
        yield server


def _walk(server: ThreadingHTTPServer, limit: int) -> list[str]:
    seen: list[str] = []
    query = f"?limit={limit}"
    while True:
        status, body = _get(server, query)
        assert status == 200
        seen += [row["key"] for row in body["merges"]]
        if not body["more"]:
            return seen
        query = f"?limit={limit}&before={body['merges'][-1]['at']}"


def test_pages_cover_the_ledger_with_no_overlap_or_gap_and_stop_at_the_24_hour_edge(
    server: ThreadingHTTPServer,
) -> None:
    seen = _walk(server, 2)

    assert len(seen) == len(set(seen)) == 7
    assert f"{8:040x}" not in seen
    assert {f"{n:040x}" for n in range(1, 8)} == set(seen)


def test_the_first_page_is_the_newest_merges_and_takes_every_merge_of_the_boundary_second(
    server: ThreadingHTTPServer,
) -> None:
    status, body = _get(server, "?limit=1")

    assert status == 200
    assert sorted(task for row in body["merges"] for task in row["tasks"]) == ["T-6", "T-7"]
    assert body["more"] is True


@pytest.mark.parametrize("query", ["?before=soon", "?limit=0", "?limit=lots", "?limit=1000"])
def test_a_before_or_limit_that_is_not_a_usable_number_is_refused(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _get(server, query)

    assert status == 400
    assert "error" in body
