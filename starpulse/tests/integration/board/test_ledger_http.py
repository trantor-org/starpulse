"""GET /api/ledger/<event>: a ledger a page at a time, newest first, back to the 24-hour edge and no further, and
the per-event stream that holds its newest page and then each change to it."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from starpulse.board.model.commit_keys import CommitKeys
from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import next_event, serve, url
from starpulse.views.page_server import PageServer

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
            "number": number,
            "repo": "o/trantor",
            "url": f"https://github.com/o/trantor/pull/{number}",
            "checks": "pass",
            "threads": 0,
            "stale": False,
            "merged": True,
            "merge_sha": f"{number:040x}",
            "merged_at": merged_at,
        }
    ]


def _get(server: PageServer, query: str, event: str = "MERGED") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/ledger/{event}{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def feed_pulls() -> dict[str, list[dict]]:
    pulls = {f"T-{n}": _pull(n, f"2026-10-07T00:0{n}:00Z") for n in range(1, 7)}
    pulls["T-7"] = _pull(7, "2026-10-07T00:06:00Z")
    pulls["T-8"] = _pull(8, "2026-10-05T00:00:00Z")
    return pulls


@pytest.fixture
def feed() -> BoardFeed:
    """Seven merges in the last 24 hours, the 7th and 6th sharing a second, and an eighth beyond the edge."""
    feed = BoardFeed(
        clock=lambda: NOW,
        machines={"board": MACHINE},
        domains={"ci": ["ci/apply"]},
        cues=[{"event": "MERGED", "dag": "ci/apply", "on": "merge", "resolves": "next", "state": "done"}],
        commit={"ci": CommitKeys(after="AFTER")},
    )
    feed.set_pulls(feed_pulls())
    return feed


@pytest.fixture
def server(tmp_path: Path, feed: BoardFeed) -> Iterator[PageServer]:
    with serve(tmp_path, feed) as server:
        yield server


def _walk(server: PageServer, limit: int) -> list[str]:
    seen: list[str] = []
    query = f"?limit={limit}"
    while True:
        status, body = _get(server, query)
        assert status == 200
        seen += [row["key"] for row in body["rows"]]
        if not body["more"]:
            return seen
        query = f"?limit={limit}&before={body['rows'][-1]['at']}"


def test_pages_cover_the_ledger_with_no_overlap_or_gap_and_stop_at_the_24_hour_edge(
    server: PageServer,
) -> None:
    seen = _walk(server, 2)

    assert len(seen) == len(set(seen)) == 7
    assert f"{8:040x}" not in seen
    assert {f"{n:040x}" for n in range(1, 8)} == set(seen)


def test_the_first_page_is_the_newest_merges_and_takes_every_merge_of_the_boundary_second(
    server: PageServer,
) -> None:
    status, body = _get(server, "?limit=1")

    assert status == 200
    assert sorted(task for row in body["rows"] for task in row["tasks"]) == ["T-6", "T-7"]
    assert body["more"] is True


@pytest.mark.parametrize("query", ["?before=soon", "?limit=0", "?limit=lots", "?limit=1000"])
def test_a_before_or_limit_that_is_not_a_usable_number_is_refused(server: PageServer, query: str) -> None:
    status, body = _get(server, query)

    assert status == 400
    assert "error" in body


def test_ledger_deferred_the_snapshot_holds_no_ledger_rows(server: PageServer) -> None:
    with urllib.request.urlopen(url(server, "/api/snapshot"), timeout=5) as resp:
        snapshot = json.loads(resp.read())

    assert "ledgers" not in snapshot
    assert snapshot["mergeStrip"] is not None


def test_ledger_deferred_the_route_pages_one_event_without_repeats_or_gaps(server: PageServer) -> None:
    seen = _walk(server, 3)

    assert len(seen) == len(set(seen)) == 7


def test_ledger_deferred_an_event_with_no_ledger_is_not_found(server: PageServer) -> None:
    assert _get(server, "", "NOT-AN-EVENT")[0] == 404
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(url(server, "/api/ledger/NOT-AN-EVENT/events"), timeout=5)
    assert refused.value.code == 404


def test_ledger_deferred_the_stream_holds_the_head_then_only_the_rows_that_change(
    server: PageServer, feed: BoardFeed
) -> None:
    with urllib.request.urlopen(url(server, "/api/ledger/MERGED/events"), timeout=5) as resp:
        name, head = next_event(resp)
        assert name == "page"
        assert len(head["rows"]) == 7
        assert head["more"] is False

        feed.set_pulls({**feed_pulls(), "T-9": _pull(9, "2026-10-07T00:08:00Z")})
        name, delta = next_event(resp)

    assert name == "rows"
    assert [row["tasks"] for row in delta["rows"]] == [["T-9"]]


def test_ledger_deferred_the_main_stream_sends_no_ledger_rows(server: PageServer, feed: BoardFeed) -> None:
    with urllib.request.urlopen(url(server, "/api/events"), timeout=5) as resp:
        assert next_event(resp)[0] == "snapshot"
        feed.set_pulls({**feed_pulls(), "T-9": _pull(9, "2026-10-07T00:08:00Z")})
        sent = dict(next_event(resp) for _ in range(2))  # pulls, ledgers

    assert set(sent["ledgers"]) <= {"mergeStrip", "mergePins"}
